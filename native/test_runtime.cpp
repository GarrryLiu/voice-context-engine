#include "runtime.hpp"
#include <atomic>
#include <iostream>
#include <stdexcept>
#include <thread>
void expect(bool value){if(!value)throw std::runtime_error("runtime invariant failed");}
std::string pop(voice::Runtime& r,int lane) {
  char data[1024];size_t n=0;uint64_t seq=0,g=0;int code=r.pop(lane,data,sizeof(data),n,seq,g);
  expect(code==0||code==1);return code==1?std::string(data,n):std::string();
}
int main(){
  for(bool optimized:{false,true}) {
    voice::Runtime r(1024,8,optimized);std::string input="你。好!tail",joined;
    for(char c:input){expect(r.append(1,&c,1,false)==1);joined+=pop(r,1);}
    expect(r.append(1,nullptr,0,true)==1);joined+=pop(r,1);expect(joined==input);
    expect(r.append(1,"\xe4",1,false)==1);expect(r.append(1,nullptr,0,true)==-1);
    expect(r.append(1,"\xbd\xa0!",3,true)==1);expect(pop(r,1)=="你!");
    expect(r.append(1,"\xff",1,false)==-1);
    voice::Runtime bounded(64,2,optimized);
    expect(bounded.append(1,"a.b.c.",6,false)==2);expect(bounded.stat(5)==0&&bounded.stat(7)==0);
    expect(bounded.append(1,"a.b.",4,false)==1);expect(pop(bounded,1)=="a.");
    expect(bounded.append(1,"c.",2,false)==1);expect(pop(bounded,1)=="b.");expect(pop(bounded,1)=="c.");
    expect(r.push(2,1,2,"bad",3)==-3);expect(r.push(2,1,0,"abcdefgh",8)==1);
    char output[8];expect(r.render(1,output,3)==3&&std::string(output,3)=="abc");
    expect(r.advance(2)==1);expect(r.push(2,1,1,"late",4)==0);
    expect(r.render(2,output,8)==0&&std::string(output,8)==std::string(8,'\0'));
    expect(r.push(2,2,0,"new",3)==1);expect(r.render(1,output,8)==0);
    expect(r.render(2,output,8)==3&&std::string(output,3)=="new");
    voice::Runtime concurrent(1024,64,optimized);std::atomic<bool> start{false};
    std::vector<std::thread> producers;
    for(int worker=0;worker<4;++worker)producers.emplace_back([&]{
      while(!start.load())std::this_thread::yield();
      for(int i=0;i<10000;++i){int code=concurrent.append(1,"x.",2,false);expect(code==0||code==1||code==2);}
    });
    start=true;concurrent.advance(2);
    for(auto& t:producers)t.join();
    expect(concurrent.stat(2)==0&&concurrent.stat(7)==0);
    expect(concurrent.append(1,"late!",5,true)==0);
  }
  std::cout<<"{\"status\":\"passed\",\"modes\":2,\"producer_threads\":4,\"checks\":\"utf8,bounds,ordering,cancel,render,concurrency\"}\n";
}
