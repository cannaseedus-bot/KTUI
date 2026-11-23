#include "grammar.h"
#include <cassert>
#include <iostream>
int main(){
 const std::string good="micronaut dog { role: \"dog\"; graph \"graph.gml\"; gate XCFE { admission: false; verification: false; closure: true; } phase Pop { op READ out field; } phase Xul { op CLOSE in field; } }";
 auto m=Kuhul::parseMicronaut(good);assert(m.phases.size()==2);
 for(const auto& bad: {"micronaut x { role: \"x\"; graph \"g\"; gate XCFE { admission: false; verification: false; closure: true; } phase Pop { op BOGUS; } }", "micronaut x { role: \"x\"; graph \"g\"; gate XCFE { admission: false; verification: false; closure: true; } phase Xul {} phase Pop {} }"}){
  bool failed=false;try{Kuhul::parseMicronaut(bad);}catch(const std::exception&){failed=true;}assert(failed);
 }
 std::cout<<"grammar tests passed\n";
}
