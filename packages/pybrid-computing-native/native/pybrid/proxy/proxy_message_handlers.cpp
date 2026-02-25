#include "pybrid/proxy/proxy_server.h"

#include <future>
#include <iostream>
#include <string>
#include <unordered_map>
#include <vector>

#include <google/protobuf/json/json.h>

#include "pybrid/proto/main.pb.h"
#include "pybrid/utils/protobuf_helpers.h"
#include "pybrid/utils/uuid.h"

namespace anabrid::pybrid::native {

BroadcastResult ProxyServer::broadcast_to_backends(
    std::vector<BackendDevice*> targets,
    std::function<pb::MessageV1(BackendDevice&)> request_factory,
    double timeout_secs) {

    struct BackendTask {
        BackendDevice* backend;
        std::future<pb::MessageV1> future;
    };

    std::vector<BackendTask> tasks;
    tasks.reserve(targets.size());

    for (auto* backend : targets) {
        if (!backend->control || !backend->control->is_connected()) continue;

        // Capture by value: request built eagerly so the factory doesn't
        // need to be thread-safe.
        pb::MessageV1 req = request_factory(*backend);
        auto* ctrl = backend->control.get();
        tasks.push_back({backend, std::async(std::launch::async,
            [ctrl, r = std::move(req), timeout_secs]() mutable {
                return ctrl->send_and_recv(r, timeout_secs);
            })});
    }

    BroadcastResult result;
    for (auto& task : tasks) {
        try {
            pb::MessageV1 resp = task.future.get();
            if (resp.has_error_message() && !result.had_error) {
                result.had_error = true;
                result.error_text = resp.error_message().description();
            }
        } catch (const std::exception& e) {
            if (!result.had_error) {
                result.had_error = true;
                result.error_text = e.what();
            }
        }
    }

    return result;
}

void ProxyServer::handle_describe(ClientSession& client, const pb::MessageV1& msg) {
    std::vector<pb::Entity> entities;
    entities.reserve(backends_.size());

    // backends_ is read-only after start(); no lock needed.
    for (auto& backend : backends_) {
        entities.push_back(backend.cached_entity);
    }

    pb::Entity merged = merge_entity_trees(entities);

    pb::MessageV1 response;
    response.set_id(msg.id());
    *response.mutable_describe_response()->mutable_entity() = std::move(merged);
    client.send(response);
}

void ProxyServer::handle_reset(ClientSession& client, const pb::MessageV1& msg) {
    std::vector<BackendDevice*> targets;
    for (auto& b : backends_) targets.push_back(&b);

    auto result = broadcast_to_backends(targets,
        [&msg](BackendDevice&) {
            pb::MessageV1 req;
            req.set_id(utils::generate_uuid());
            *req.mutable_reset_command() = msg.reset_command();
            return req;
        });

    pb::MessageV1 response;
    response.set_id(msg.id());
    if (result.had_error) {
        response.mutable_error_message()->set_description(result.error_text);
    } else {
        response.mutable_reset_response();
    }
    client.send(response);
}

void ProxyServer::handle_extract(ClientSession& client, const pb::MessageV1& msg) {
    const std::string& path = msg.extract_command().entity().path();
    BackendDevice* backend = find_backend_for_path(path);

    if (!backend || !backend->control || !backend->control->is_connected()) {
        send_error_to_client(client, msg.id(),
                             "No backend found for entity path: " + path);
        return;
    }

    try {
        pb::MessageV1 req;
        req.set_id(utils::generate_uuid());
        *req.mutable_extract_command() = msg.extract_command();

        pb::MessageV1 resp = backend->control->send_and_recv(req, BACKEND_REQUEST_TIMEOUT_SECS);
        resp.set_id(msg.id());
        client.send(resp);
    } catch (const std::exception& e) {
        send_error_to_client(client, msg.id(),
                             std::string("Extract failed: ") + e.what());
    }
}

void ProxyServer::handle_config(ClientSession& client, const pb::MessageV1& msg) {
    const pb::ConfigBundle& bundle = msg.config_command().bundle();

    if (debug_) {
        std::cerr << "[ProxyServer] DEBUG: handle_config — "
                  << bundle.configs_size() << " config entries:\n";
        for (int i = 0; i < bundle.configs_size(); ++i) {
            std::string json_str;
            auto status = google::protobuf::json::MessageToJsonString(
                bundle.configs(i), &json_str,
                google::protobuf::json::PrintOptions{
                    .add_whitespace = true,
                    .always_print_fields_with_no_presence = true,
                });
            if (status.ok()) {
                std::cerr << "  [" << i << "] " << json_str << "\n";
            } else {
                std::cerr << "  [" << i << "] (JSON conversion failed: "
                          << status.message() << ")\n";
            }
        }
        const auto& cmd = msg.config_command();
        std::cerr << "  flags: reset_before=" << cmd.reset_before()
                  << " sh_kludge=" << cmd.sh_kludge() << "\n";
    }

    // Phase 1: Route all config entries to backends. Unroutable paths cause
    // a full reject — never send partial configs.
    std::unordered_map<BackendDevice*, pb::ConfigBundle> per_backend;
    std::vector<std::string> unroutable_paths;

    for (int i = 0; i < bundle.configs_size(); ++i) {
        const pb::Config& cfg = bundle.configs(i);
        const std::string& path = cfg.entity().path();

        // Config entries without an entity path (global settings) are broadcast
        // to all backends — they don't participate in MAC-based routing.
        if (path.empty()) {
            for (auto& backend : backends_) {
                *per_backend[&backend].add_configs() = cfg;
            }
            continue;
        }

        BackendDevice* backend = find_backend_for_path(path);
        if (!backend) {
            unroutable_paths.push_back(path);
            continue;
        }
        *per_backend[backend].add_configs() = cfg;
    }

    if (!unroutable_paths.empty()) {
        std::string reject_text = "Config rejected — no backend found for entity path(s): ";
        for (size_t i = 0; i < unroutable_paths.size(); ++i) {
            if (i > 0) reject_text += ", ";
            reject_text += unroutable_paths[i];
        }
        send_error_to_client(client, msg.id(), reject_text);
        return;
    }

    // Phase 2: Send per-backend config commands in parallel.
    std::vector<BackendDevice*> targets;
    for (auto& [backend_ptr, sub_bundle] : per_backend) {
        targets.push_back(backend_ptr);
    }

    auto result = broadcast_to_backends(targets,
        [&per_backend, &msg](BackendDevice& backend) {
            pb::MessageV1 req;
            req.set_id(utils::generate_uuid());
            pb::ConfigCommand* config_cmd = req.mutable_config_command();
            *config_cmd->mutable_bundle() = per_backend[&backend];
            config_cmd->set_reset_before(msg.config_command().reset_before());
            config_cmd->set_sh_kludge(msg.config_command().sh_kludge());
            return req;
        });

    pb::MessageV1 response;
    response.set_id(msg.id());
    if (result.had_error) {
        response.mutable_error_message()->set_description(result.error_text);
    } else {
        response.mutable_config_response();
    }
    client.send(response);
}

void ProxyServer::handle_start_run(ClientSession& client, const pb::MessageV1& msg) {
    // Advance the run generation and reset per-run counters so that stale
    // callbacks from the previous run are discarded. Also clear done_received
    // so the session timeout does not fire mid-run.
    run_id_.fetch_add(1, std::memory_order_acq_rel);
    take_off_count_.store(0, std::memory_order_release);
    done_count_.store(0, std::memory_order_release);
    client.done_received.store(false, std::memory_order_release);

    for (auto& backend : backends_) {
        if (backend.data_channel) {
            backend.data_channel->reset_sequence_tracking();
        }
    }

    if (debug_) {
        std::string json_str;
        auto status = google::protobuf::json::MessageToJsonString(
            msg.start_run_command(), &json_str,
            google::protobuf::json::PrintOptions{
                .add_whitespace = true,
                .always_print_fields_with_no_presence = true,
            });
        std::cerr << "[ProxyServer] DEBUG: handle_start_run — Session "
                  << client.session_id_ << "\n";
        if (status.ok()) {
            std::cerr << "  StartRunCommand: " << json_str << "\n";
        } else {
            std::cerr << "  (JSON failed: " << status.message() << ")\n";
        }
    }

    std::vector<BackendDevice*> targets;
    for (auto& b : backends_) targets.push_back(&b);

    auto result = broadcast_to_backends(targets,
        [&msg](BackendDevice&) {
            pb::MessageV1 req;
            req.set_id(utils::generate_uuid());
            *req.mutable_start_run_command() = msg.start_run_command();
            return req;
        });

    pb::MessageV1 response;
    response.set_id(msg.id());
    if (result.had_error) {
        response.mutable_error_message()->set_description(result.error_text);
    } else {
        response.mutable_start_run_response();
    }
    client.send(response);
}

void ProxyServer::handle_auth(ClientSession& client, const pb::MessageV1& msg) {
    if (requires_auth_) {
        pb::MessageV1 response;
        response.set_id(msg.id());

        const std::string& token = msg.auth_request().bearer().token();
        if (token == auth_token_) {
            client.authenticated_ = true;
            response.mutable_success_message();
        } else {
            response.mutable_error_message()->set_description("Authentication failed");
        }
        client.send(response);
        return;
    }

    // Auth is always handled at the proxy level, never forwarded to backends.
    // When requires_auth_ is false, accept any token with a SuccessMessage.
    pb::MessageV1 response;
    response.set_id(msg.id());
    response.mutable_success_message();
    client.send(response);
}

void ProxyServer::handle_calibrate(ClientSession& client, const pb::MessageV1& msg) {
    if (debug_) {
        const auto& cfg = msg.calibration_command().config();
        std::cerr << "[ProxyServer] DEBUG: handle_calibrate — Session "
                  << client.session_id_ << "\n"
                  << "  math=" << pb::CalibrationConfig_Kind_Name(cfg.math())
                  << " gain=" << pb::CalibrationConfig_Kind_Name(cfg.gain())
                  << " offset=" << pb::CalibrationConfig_Kind_Name(cfg.offset())
                  << " leader=" << (cfg.has_leader() ? cfg.leader().path() : "<none>")
                  << "\n";
    }

    std::vector<BackendDevice*> targets;
    for (auto& b : backends_) targets.push_back(&b);

    auto result = broadcast_to_backends(targets,
        [&msg](BackendDevice&) {
            pb::MessageV1 req;
            req.set_id(utils::generate_uuid());
            *req.mutable_calibration_command() = msg.calibration_command();
            return req;
        });

    pb::MessageV1 response;
    response.set_id(msg.id());
    if (result.had_error) {
        response.mutable_error_message()->set_description(result.error_text);
    } else {
        response.mutable_calibration_response();
    }
    client.send(response);
}

void ProxyServer::handle_udp_streaming(
    ClientSession& client, const pb::MessageV1& msg) {
    send_error_to_client(
        client,
        msg.id(),
        "UDP streaming is not supported by the proxy; data is delivered over TCP.");
}

BackendDevice* ProxyServer::find_backend_for_path(const std::string& entity_path) {
    if (entity_path.empty()) return nullptr;

    // Extract the MAC address: first segment before any '/'.
    // Strip optional leading '/' first.
    size_t start = (entity_path[0] == '/') ? 1 : 0;
    auto slash_pos = entity_path.find('/', start);
    std::string mac = (slash_pos != std::string::npos)
        ? entity_path.substr(start, slash_pos - start)
        : entity_path.substr(start);

    // carrier_paths are stored without leading '/'.
    auto it = path_to_backend_.find(mac);
    if (it != path_to_backend_.end()) return it->second;

    return nullptr;
}

pb::Entity ProxyServer::merge_entity_trees(const std::vector<pb::Entity>& entities) {
    if (entities.empty()) {
        return pb::Entity{};
    }
    if (entities.size() == 1) {
        return entities[0];
    }

    pb::Entity root;
    root.set_id("/");
    for (const auto& entity : entities) {
        *root.add_children() = entity;
    }
    return root;
}

void ProxyServer::send_error_to_client(
    ClientSession& client,
    const std::string& request_id,
    const std::string& error_text) {
    if (debug_) {
        std::cerr << "[ProxyServer] DEBUG: Proxy error for session "
                  << client.session_id_ << ": " << error_text << "\n";
    }
    pb::MessageV1 error_msg;
    if (!request_id.empty()) {
        error_msg.set_id(request_id);
    }
    error_msg.mutable_error_message()->set_description(error_text);
    client.send(error_msg);
}

}  // namespace anabrid::pybrid::native
