#include "grammar.h"
#include <cctype>
#include <algorithm>
#include <set>
#include <sstream>
#include <utility>

namespace Kuhul {
namespace {
struct Token { std::string value; bool quoted=false; size_t line=1; };
std::vector<Token> lex(const std::string& src) {
 std::vector<Token> out; size_t i=0, line=1;
 while (i<src.size()) {
  unsigned char c=static_cast<unsigned char>(src[i]);
  if (std::isspace(c)) { if(c=='\n') ++line; ++i; continue; }
  if (c=='#' || (c=='/' && i+1<src.size() && src[i+1]=='/')) {
   while(i<src.size() && src[i]!='\n') ++i; continue;
  }
  if (c=='"') {
   size_t start=line; ++i; std::string value; bool closed=false;
   while(i<src.size()) {
    char ch=src[i++];
    if(ch=='"') {closed=true; break;}
    if(ch=='\n') ++line;
    if(ch=='\\') {
     if(i==src.size()) throw std::runtime_error("Unterminated string escape");
     char e=src[i++];
     if(e=='n') value+='\n'; else if(e=='t') value+='\t';
     else if(e=='"'||e=='\\') value+=e;
     else throw std::runtime_error("Unsupported string escape");
    } else value+=ch;
   }
   if(!closed) throw std::runtime_error("Unterminated string at line "+std::to_string(start));
   out.push_back({value,true,start}); continue;
  }
  if(i+1<src.size() && ((src[i]=='=' && src[i+1]=='>') || (src[i]=='-' && src[i+1]=='>'))) {
   out.push_back({src.substr(i,2),false,line}); i+=2; continue;
  }
  if(c=='{'||c=='}'||c==':'||c==';') {out.push_back({std::string(1,char(c)),false,line}); ++i; continue;}
  if(std::isalpha(c)||c=='_') {
   size_t start=i++;
   while(i<src.size()) {
    unsigned char d=static_cast<unsigned char>(src[i]);
    if(std::isalnum(d)||d=='_'||d=='.'||d=='-') ++i; else break;
   }
   out.push_back({src.substr(start,i-start),false,line}); continue;
  }
  if(std::isdigit(c)||c=='-') {
   size_t start=i++;
   while(i<src.size() && (std::isdigit(static_cast<unsigned char>(src[i]))||src[i]=='.')) ++i;
   out.push_back({src.substr(start,i-start),false,line}); continue;
  }
  throw std::runtime_error("Unexpected character at line "+std::to_string(line));
 }
 return out;
}
class Parser {
 std::vector<Token> tokens; size_t at=0;
 const Token& peek() const { if(at>=tokens.size()) throw std::runtime_error("Unexpected end of input"); return tokens[at]; }
 bool is(const std::string& s) const {return at<tokens.size() && !tokens[at].quoted && tokens[at].value==s;}
 bool take(const std::string& s) {if(is(s)){++at;return true;}return false;}
 void expect(const std::string& s) {if(!take(s)) throw std::runtime_error("Expected '"+s+"' at line "+std::to_string(at<tokens.size()?tokens[at].line:0));}
 std::string ident() {
  const auto& t=peek();
  if(t.quoted || t.value.empty() || !(std::isalpha(static_cast<unsigned char>(t.value[0]))||t.value[0]=='_'))
   throw std::runtime_error("Expected identifier at line "+std::to_string(t.line));
  ++at; return t.value;
 }
 std::string quoted() {const auto& t=peek(); if(!t.quoted) throw std::runtime_error("Expected string at line "+std::to_string(t.line)); ++at; return t.value;}
 std::string literal() {
  const auto& t=peek();
  if(t.quoted){++at;return t.value;}
  if(t.value=="true"||t.value=="false"||(!t.value.empty()&&(std::isdigit(static_cast<unsigned char>(t.value[0]))||t.value[0]=='-'))){++at;return t.value;}
  throw std::runtime_error("Expected literal at line "+std::to_string(t.line));
 }
 bool boolean() {if(take("true"))return true;expect("false");return false;}
 Step step() {
  expect("op"); Step s; s.opcode=ident();
  if(take("in")) s.input=ident();
  if(take("out")) s.output=ident();
  if(take("when")) {s.when.present=true; s.when.name=ident(); s.when.comparator=ident(); s.when.value=literal();}
  expect(";");return s;
 }
public:
 explicit Parser(const std::string& s):tokens(lex(s)){}
 MicronautDecl parse() {
  MicronautDecl m;
  expect("micronaut");m.name=ident();expect("{");
  expect("role");expect(":");m.role=quoted();expect(";");
  expect("graph");m.graph=quoted();expect(";");
  if(take("data")){m.has_data=true;m.data=quoted();expect(";");}
  while(take("pattern")) {PatternDecl p;p.pattern=quoted();expect("=>");p.kind=ident();p.target=ident();expect(";");m.patterns.push_back(p);}
  while(take("capability")){NamedDecl c;c.name=ident();expect(":");c.kind=ident();expect(";");m.capabilities.push_back(c);}
  while(take("bind")){BindingDecl b;b.name=ident();expect(":");b.type=ident();expect("->");b.target=ident();expect(";");m.bindings.push_back(b);}
  while(take("route")){RouteDecl r;r.from=ident();expect("->");r.to=ident();expect(";");m.routes.push_back(r);}
  expect("gate");expect("XCFE");expect("{");
  expect("admission");expect(":");m.admission=boolean();expect(";");
  expect("verification");expect(":");m.verification=boolean();expect(";");
  expect("closure");expect(":");m.closure=boolean();expect(";");expect("}");
  while(take("phase")) {
   PhaseDecl p;p.name=ident();expect("{");
   while(!is("}")) p.steps.push_back(step());
   expect("}");m.phases.push_back(std::move(p));
  }
  expect("}");
  if(at!=tokens.size()) throw std::runtime_error("Trailing tokens at line "+std::to_string(peek().line));
  validateMicronaut(m);return m;
 }
};
void requireMember(const std::string& value, const std::set<std::string>& values,const std::string& label) {
 if(!values.count(value)) throw std::runtime_error("Invalid "+label+": "+value);
}
}
void validateMicronaut(const MicronautDecl& m) {
 static const std::set<std::string> cap={"read","write","ask","respond","compute"};
 static const std::set<std::string> types={"string","vector","tensor","field","signal","graph","number","boolean"};
 static const std::set<std::string> ops={"READ","BIND","MAP","FILTER","PI","MATCH","RESOLVE","SRAI","RANK","XCFE","ACCUMULATE","FOLD","REDUCE","ASK","RESPOND","PATCH","CLOSE"};
 static const std::set<std::string> cmps={"eq","ne","contains","exists","gt","ge","lt","le"};
 static const std::vector<std::string> phases={"Pop","Wo","Yax","Sek","Chen","Xul"};
 std::set<std::string> seen;
 for(const auto& c:m.capabilities){requireMember(c.kind,cap,"capability kind");if(!seen.insert(c.name).second)throw std::runtime_error("Duplicate capability: "+c.name);}
 seen.clear();for(const auto& b:m.bindings){requireMember(b.type,types,"binding type");if(!seen.insert(b.name).second)throw std::runtime_error("Duplicate binding: "+b.name);}
 int last=-1;
 for(const auto& p:m.phases){
  auto it=std::find(phases.begin(),phases.end(),p.name);
  if(it==phases.end())throw std::runtime_error("Unknown phase: "+p.name);
  int idx=static_cast<int>(it-phases.begin());
  if(idx<=last)throw std::runtime_error("Duplicate or out-of-order phase: "+p.name);
  last=idx;
  for(const auto& s:p.steps){requireMember(s.opcode,ops,"opcode");if(s.when.present)requireMember(s.when.comparator,cmps,"comparator");}
 }
 for(const auto& p:m.patterns) requireMember(p.kind,{"srai","intent"},"pattern kind");
}
MicronautDecl parseMicronaut(const std::string& source){return Parser(source).parse();}
}
