#include "grammar.h"
#include <fstream>
#include <iostream>
#include <iterator>
int main(int argc,char** argv) {
 if(argc!=2){std::cerr<<"usage: micronaut-parse file.micronaut\n";return 2;}
 std::ifstream file(argv[1],std::ios::binary);
 if(!file){std::cerr<<"Cannot open input\n";return 2;}
 try {
  auto m=Kuhul::parseMicronaut(std::string(std::istreambuf_iterator<char>(file),{}));
  std::cout<<"VALID micronaut="<<m.name<<" phases="<<m.phases.size()<<"\n";
  for(const auto& p:m.phases)std::cout<<"  "<<p.name<<" operations="<<p.steps.size()<<"\n";
  return 0;
 }catch(const std::exception& e){std::cerr<<"INVALID "<<e.what()<<"\n";return 1;}
}
