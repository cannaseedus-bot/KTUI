#pragma once
#include <string>
#include <vector>
#include <stdexcept>
namespace Kuhul {
struct PatternDecl { std::string pattern, kind, target; };
struct NamedDecl { std::string name, kind; };
struct BindingDecl { std::string name, type, target; };
struct RouteDecl { std::string from, to; };
struct Condition { std::string name, comparator, value; bool present=false; };
struct Step { std::string opcode, input, output; Condition when; };
struct PhaseDecl { std::string name; std::vector<Step> steps; };
struct MicronautDecl {
 std::string name, role, graph, data;
 bool has_data=false;
 bool admission=false, verification=false, closure=false;
 std::vector<PatternDecl> patterns;
 std::vector<NamedDecl> capabilities;
 std::vector<BindingDecl> bindings;
 std::vector<RouteDecl> routes;
 std::vector<PhaseDecl> phases;
};
// Parses the text DSL in grammar/micronaut.ebnf. Throws std::runtime_error on invalid syntax.
MicronautDecl parseMicronaut(const std::string& source);
// Structural checks only; no execution, filesystem I/O, graph resolution or host grants.
void validateMicronaut(const MicronautDecl& declaration);
}
