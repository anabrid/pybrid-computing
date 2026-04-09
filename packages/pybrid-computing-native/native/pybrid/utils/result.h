#pragma once

#include <cassert>
#include <sstream>
#include <type_traits>
#include <variant>

#define TRY(result) \
  ({ \
    decltype(result) _result(std::move(result)); \
    if (_result.is_err()) return std::move(_result); \
    std::move(_result.ok_value()); \
  })

#define UNWRAP(result)                                \
  ({                                                  \
    if(result.is_err()){                              \
      std::cerr << (result).err_value() << std::endl; \
      assert(false);                                  \
    }                                                 \
    (result).ok_value();                              \
  })

template<typename Stream>
static void concat_helper(Stream& ss)
{
}

template<typename Stream, typename T, typename... Args>
static void concat_helper(Stream& ss, T&& t, Args&&... args)
{
  ss << std::forward<T>(t);
  concat_helper(ss, std::forward<Args>(args)...);
}

/**
 * A class that represents either a successful value of type V or an error of type E.
 * Similar to Rust's Result type, it provides a way to handle operations that can fail.
 *
 * Example usage:
 *
 * // Function that returns a Result
 * Result<int, std::string> divide(int a, int b) {
 *   if (b == 0) {
 *     return Result<int, std::string>::err("Division by zero");
 *   }
 *   return Result<int, std::string>::ok(a / b);
 * }
 *
 * // Using TRY macro for early return on error
 * Result<double, std::string> complex_calculation(int x, int y) {
 *   auto div_result = TRY(divide(x, y));
 *   return Result<double, std::string>::ok(div_result * 2.0);
 * }
 */
template<class V, class E = std::string>
class Result
{
  std::variant<V, E> result;

  template<class, class>
  friend class Result;

  mutable bool err_unused = false;

  explicit Result(std::variant<V, E> result)
  : result(std::move(result))
  {
    err_unused = is_err();
  }

public:

  Result(V ok_value)
  : result(std::variant<V, E>(std::in_place_index<0>, std::move(ok_value)))
  {
  }

  template<typename O, std::enable_if_t<!std::is_same_v<V, O>, int> = 0>
  Result(Result<O, E>&& other_result)
  : result(std::variant<V, E>(std::in_place_index<1>, ""))
  {
    assert(other_result.is_err());
    result = std::move(other_result.err_value());
  }

  Result(Result&& other_result)
  : result(std::move(other_result.result))
  {
    err_unused              = other_result.err_unused;
    other_result.err_unused = false;
  }

  ~Result()
  {
    assert(!err_unused);
  }

  static Result<V, E> ok(V ok_value)
  {
    return Result(std::variant<V, E>(std::in_place_index<0>, std::move(ok_value)));
  }

  template<typename U = V>
  static std::enable_if_t<std::is_same_v<U, std::monostate>, Result<V, E>> ok()
  {
    return ok({});
  }

  static Result<V, E> err(E err_value)
  {
    return Result(std::variant<V, E>(std::in_place_index<1>, std::move(err_value)));
  }

  template<typename... Args>
  static std::enable_if_t<std::is_same_v<E, std::string>, Result<V, E>>
  err_concat(Args&&... args)
  {
    std::ostringstream oss;
    concat_helper(oss, std::forward<Args>(args)...);
    return err(oss.str());
  }

  template<typename... Args>
  static std::enable_if_t<std::is_same_v<E, std::string>, Result<V, E>>
  err_fmt(const char* format, Args... args)
  {
    // Calculate required buffer size
    int size = std::snprintf(nullptr, 0, format, args...);
    if(size < 0)
    {
      return err("Format error");
    }

    // Create string with required size and format into it
    std::string result(size + 1, '\0');
    std::snprintf(&result[0], size + 1, format, args...);
    result.resize(size); // Remove null terminator from string length
    return err(result);
  }

  [[nodiscard]] bool is_ok() const
  {
    return result.index() == 0;
  }

  [[nodiscard]] bool is_err() const
  {
    err_unused = false;
    return result.index() == 1;
  }

  [[nodiscard]] V* as_ok()
  {
    if(!is_ok())
      return nullptr;

    return &ok_value();
  }

  [[nodiscard]] E* as_err()
  {
    if(is_ok())
      return nullptr;

    return &err_value();
  }

  [[nodiscard]] V& ok_value()
  {
    return std::get<0>(result);
  }

  [[nodiscard]] E& err_value()
  {
    err_unused = false;
    return std::get<1>(result);
  }

  operator bool() const
  {
    return is_ok();
  }
};

using UnitResult = Result<std::monostate>;
