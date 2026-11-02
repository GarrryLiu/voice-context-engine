#include "runtime.hpp"
#include <chrono>
#include <cmath>
#include <iostream>
#include <stdexcept>
int main(){
  std::cout<<"{\"kind\":\"cpp_direct_sentence_cpu_ablation\",\"runs\":[";bool first=true;
  for(bool optimized:{false,true}) {
    voice::Runtime runtime(32768,256,optimized);std::string input(16000,'a');input+='.';
    std::vector<double> samples;
    for(uint64_t trial=0;trial<25;++trial) {
      runtime.advance(trial+2);auto start=std::chrono::steady_clock::now();
      for(size_t i=0;i<input.size();i+=32) {
        auto n=std::min(size_t(32),input.size()-i);
        if(runtime.append(trial+2,input.data()+i,n,false)!=1)throw std::runtime_error("append failed");
      }
      if(runtime.append(trial+2,nullptr,0,true)!=1)throw std::runtime_error("flush failed");
      char out[32768];size_t n=0;uint64_t seq=0,g=0;
      if(runtime.pop(1,out,sizeof(out),n,seq,g)!=1||std::string(out,n)!=input)throw std::runtime_error("byte mismatch");
      samples.push_back(std::chrono::duration<double,std::micro>(std::chrono::steady_clock::now()-start).count());
    }
    std::sort(samples.begin(),samples.end());
    if(!first)std::cout<<",";first=false;
    std::cout<<"{\"incremental\":"<<(optimized?"true":"false")<<",\"samples\":25,\"median_document_us\":"<<samples[12]<<",\"p95_document_us\":"<<samples[size_t(std::ceil(.95*samples.size()))-1]<<",\"scan_positions_total\":"<<runtime.stat(10)<<"}";
  }
  std::cout<<"]}\n";
}
