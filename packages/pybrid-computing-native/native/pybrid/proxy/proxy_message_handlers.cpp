#include "pybrid/proxy/proxy_server.h"

#include <algorithm>
#include <chrono>
#include <future>
#include <iostream>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

#include <google/protobuf/json/json.h>

#include "pybrid/proto/main.pb.h"
#include "pybrid/utils/protobuf_helpers.h"
#include "pybrid/utils/uuid.h"

namespace {

/// Sort EntitySpecification items within a module by CarrierLocationV0
/// (stack first, then carrier). Non-specification items are left in place.
void sort_module_by_location(pb::Module& module) {
    auto* items = module.mutable_items();

    // Partition: collect indices of entity_specification items.
    std::vector<int> spec_indices;
    for (int i = 0; i < items->size(); ++i) {
        if (items->at(i).has_entity_specification()) {
            spec_indices.push_back(i);
        }
    }
    if (spec_indices.size() <= 1) return;

    // Sort the spec indices by (stack, carrier).
    std::stable_sort(spec_indices.begin(), spec_indices.end(),
        [&items](int a, int b) {
            auto key = [](const pb::Item& item) -> std::pair<uint32_t, uint32_t> {
                const auto& e = item.entity_specification().entity();
                if (e.has_location_v0())
                    return {e.location_v0().stack(), e.location_v0().carrier()};
                return {UINT32_MAX, UINT32_MAX};
            };
            return key(items->at(a)) < key(items->at(b));
        });

    // Apply the permutation via a temporary copy of the spec items.
    std::vector<pb::Item> sorted_specs;
    sorted_specs.reserve(spec_indices.size());
    for (int idx : spec_indices) {
        sorted_specs.push_back(items->at(idx));
    }

    // Write them back into their original slot positions.
    std::vector<int> slots(spec_indices);
    std::sort(slots.begin(), slots.end());
    for (size_t i = 0; i < slots.size(); ++i) {
        *items->Mutable(slots[i]) = std::move(sorted_specs[i]);
    }
}

}  // anonymous namespace

namespace anabrid::pybrid::native {

BroadcastResult ProxyServer::broadcast_to_backends(
    std::vector<BackendDevice*> targets,
    std::function<pb::MessageV1(BackendDevice&)> request_factory,
    double timeout_secs,
    bool include_responses) {

    struct BackendTask {
        BackendDevice* backend;
        std::future<pb::MessageV1> future;
    };

    std::vector<BackendTask> tasks;
    tasks.reserve(targets.size());

    BroadcastResult result;
    for (auto* backend : targets) {
        if (!backend->control || !backend->control->is_connected()) {
            result.had_error = true;
            result.error_text = "Backend " + backend->host + " not connected!";
            continue;
        }

        // Capture by value: request built eagerly so the factory doesn't
        // need to be thread-safe.
        pb::MessageV1 req = request_factory(*backend);
        auto* ctrl = backend->control.get();
        tasks.push_back({backend, std::async(std::launch::async,
            [ctrl, r = std::move(req), timeout_secs]() mutable {
                return ctrl->send_and_recv(r, timeout_secs);
            })});
    }

    for (auto& task : tasks) {
        try {
            pb::MessageV1 resp = task.future.get();

            if(include_responses)
                result.responses.emplace_back(resp);

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

    if (path.empty()) {
        // No entity path specified — aggregate cached modules from all backends.
        pb::Module merged;
        for (auto& backend : backends_) {
            for (const auto& item : backend.cached_module.items()) {
                *merged.add_items() = item;
            }
        }

        sort_module_by_location(merged);

        pb::MessageV1 response;
        response.set_id(msg.id());
        *response.mutable_extract_response()->mutable_module() = std::move(merged);
        client.send(response);
        return;
    }

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
        if (resp.has_extract_response()) {
            sort_module_by_location(*resp.mutable_extract_response()->mutable_module());
        }
        resp.set_id(msg.id());
        client.send(resp);
    } catch (const std::exception& e) {
        send_error_to_client(client, msg.id(),
                             std::string("Extract failed: ") + e.what());
    }
}

void ProxyServer::handle_config(ClientSession& client, const pb::MessageV1& msg) {
    const pb::Module& module = msg.config_command().module();

    if (debug_) {
        std::cerr << "[ProxyServer] DEBUG: handle_config — "
                  << module.items_size() << " config entries:\n";
        for (int i = 0; i < module.items_size(); ++i) {
            std::string json_str;
            google::protobuf::json::PrintOptions opts;
            opts.add_whitespace = true;
            opts.always_print_fields_with_no_presence = true;
            auto status = google::protobuf::json::MessageToJsonString(
                module.items(i), &json_str, opts);
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
    std::unordered_map<BackendDevice*, pb::Module> per_backend;
    std::vector<std::string> unroutable_paths;

    for (int i = 0; i < module.items_size(); ++i) {
        const pb::Item& cfg = module.items(i);
        const std::string& path = cfg.entity().path();

        // Config entries without an entity path (global settings) are broadcast
        // to all backends — they don't participate in MAC-based routing.
        if (path.empty()) {
            for (auto& backend : backends_) {
                *per_backend[&backend].add_items() = cfg;
            }
            continue;
        }

        BackendDevice* backend = find_backend_for_path(path);
        if (!backend) {
            unroutable_paths.push_back(path);
            continue;
        }
        *per_backend[backend].add_items() = cfg;
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
    for (auto& [backend_ptr, sub_module] : per_backend) {
        targets.push_back(backend_ptr);
    }

    auto result = broadcast_to_backends(targets,
        [&per_backend, &msg](BackendDevice& backend) {
            pb::MessageV1 req;
            req.set_id(utils::generate_uuid());
            pb::ConfigCommand* config_cmd = req.mutable_config_command();
            *config_cmd->mutable_module() = per_backend[&backend];
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
        google::protobuf::json::PrintOptions opts;
        opts.add_whitespace = true;
        opts.always_print_fields_with_no_presence = true;
        auto status = google::protobuf::json::MessageToJsonString(
            msg.start_run_command(), &json_str, opts);
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

void ProxyServer::handle_register_external_entities(
    ClientSession& client, const pb::MessageV1& msg) {
    pb::MessageV1 response;
    response.set_id(msg.id());
    response.mutable_success_message();
    client.send(response);
}

void ProxyServer::handle_ping(ClientSession& client) {
    std::string error;
    for (auto& backend : backends_) {
        try {
            backend.control->ping(BACKEND_REQUEST_TIMEOUT_SECS);
        } catch (const std::exception& e) {
            if (error.empty()) {
                error = "Ping failed for " + backend.host + ":" +
                        std::to_string(backend.port) + ": " + e.what();
            }
        }
    }

    pb::Envelope response;
    if (error.empty()) {
        response.mutable_generic()->mutable_ping_response();
    } else {
        response.mutable_message_v1()->mutable_error_message()
            ->set_description(error);
    }

    std::string serialized;
    if (response.SerializeToString(&serialized)) {
        try {
            client.transport()->send(serialized.data(), serialized.size());
        } catch (const std::runtime_error&) {
            // Client disconnected — response is lost, session will end.
        }
    }
}

void ProxyServer::handle_update(
    ClientSession& client, const pb::MessageV1& msg) {
    const auto& update_cmd = msg.update_command();

    constexpr std::chrono::milliseconds REBOOT_GRACE{2000};
    constexpr std::chrono::milliseconds RECONNECT_TIMEOUT{20000};

    const char* kind = update_cmd.has_begin()  ? "begin"  :
                       update_cmd.has_write()   ? nullptr  :
                       update_cmd.has_verify()  ? "verify" :
                       update_cmd.has_commit()  ? "commit" :
                       update_cmd.has_abort()   ? "abort"  : "unknown";
    if (kind) {
        std::lock_guard<std::mutex> lock(log_mutex_);
        std::cerr << "[ProxyServer] Update: " << kind << "\n";
    }

    std::vector<BackendDevice*> targets;
    for (auto& b : backends_) targets.push_back(&b);

    if (update_cmd.has_commit()) {

        auto result = broadcast_to_backends(targets,
            [&msg](BackendDevice&) {
                pb::MessageV1 req;
                req.set_id(utils::generate_uuid());
                *req.mutable_update_command() = msg.update_command();
                return req;
            },
            20.0,
            true);

        // Reply to client immediately — the device answers before rebooting.
        // TCP closes during commit are expected (devices reboot after
        // applying firmware), so we always report success and proceed to
        // the REBOOTING + reconnect phase.
        pb::MessageV1 response;
        response.set_id(msg.id());
        response.mutable_update_response()->mutable_success();
        client.send(response);

        // Mark all backends REBOOTING so the background reconnect_loop
        // and the session watchdog leave them alone during the reboot.
        for (auto* backend : targets) {
            set_backend_health(*backend, BackendHealth::REBOOTING);
        }

        std::this_thread::sleep_for(REBOOT_GRACE);

        std::vector<std::future<bool>> futures;
        futures.reserve(targets.size());
        for (auto* backend : targets) {
            futures.push_back(std::async(std::launch::async,
                [this, backend]() {
                    return reconnect_backend(*backend, RECONNECT_TIMEOUT);
                }));
        }

        for (size_t i = 0; i < futures.size(); ++i) {
            bool ok = futures[i].get();
            set_backend_health(*targets[i],
                ok ? BackendHealth::HEALTHY : BackendHealth::DEAD);
        }
        return;
    }

    // Non-commit paths: broadcast and relay results.
    auto result = broadcast_to_backends(targets,
        [&msg](BackendDevice&) {
            pb::MessageV1 req;
            req.set_id(utils::generate_uuid());
            *req.mutable_update_command() = msg.update_command();
            return req;
        },
        5.0,
        update_cmd.has_begin());

    if (result.had_error) {
        pb::MessageV1 response;
        response.set_id(msg.id());
        response.mutable_update_response()->mutable_failure()->set_reason(
            result.error_text);
        client.send(response);
        return;
    }

    if (update_cmd.has_begin()) {
        // Use the minimum chunk size so no backend gets oversized writes.
        size_t min_chunk = SIZE_MAX;
        for (auto& resp : result.responses) {
            min_chunk = std::min(min_chunk,
                static_cast<size_t>(resp.update_response().ack().chunk_size()));
        }

        pb::MessageV1 response;
        response.set_id(msg.id());
        response.mutable_update_response()->mutable_ack()->set_chunk_size(min_chunk);
        client.send(response);
        return;
    }

    pb::MessageV1 response;
    response.set_id(msg.id());
    response.mutable_update_response()->mutable_success();
    client.send(response);
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
