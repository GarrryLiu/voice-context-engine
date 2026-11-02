#pragma once
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstring>
#include <deque>
#include <mutex>
#include <string>
#include <vector>

namespace voice {
struct Frame {uint64_t sequence;std::string data;size_t offset=0;};
// One active interaction per instance. Logical payload bounds exclude allocator metadata.
class Runtime {
  std::mutex mutex_;
  uint64_t generation_=1,stale_=0,pressure_=0,scanned_=0,rendered_=0;
  size_t cap_,items_,scan_=0,valid_=0;
  bool incremental_;
  std::string pending_;
  std::array<std::deque<Frame>,3> queues_;
  std::array<size_t,3> bytes_{};
  std::array<uint64_t,3> next_{};
  static bool utf8(const std::string& s,size_t start,size_t& complete) {
    size_t i=start;
    while(i<s.size()) {
      unsigned char c=s[i];size_t n=c<0x80?1:c>=0xc2&&c<=0xdf?2:c>=0xe0&&c<=0xef?3:c>=0xf0&&c<=0xf4?4:0;
      if(!n)return false;
      for(size_t j=1;j<n&&i+j<s.size();++j) {
        unsigned char x=s[i+j];if(x<0x80||x>0xbf)return false;
        if(j==1&&((c==0xe0&&x<0xa0)||(c==0xed&&x>0x9f)||(c==0xf0&&x<0x90)||(c==0xf4&&x>0x8f)))return false;
      }
      if(i+n>s.size()){complete=i;return true;}
      i+=n;
    }
    complete=i;return true;
  }
  bool current(uint64_t g){if(g==generation_)return true;++stale_;return false;}
public:
  Runtime(size_t bytes,size_t items,bool incremental):cap_(bytes),items_(items),incremental_(incremental){}
  int advance(uint64_t g) {
    std::lock_guard<std::mutex> lock(mutex_);
    if(g<generation_)return 0;
    if(g==generation_)return 1;
    generation_=g;pending_.clear();scan_=valid_=0;
    for(auto& q:queues_)q.clear();bytes_.fill(0);next_.fill(0);return 1;
  }
  // 1 accepted, 0 stale, 2 backpressure, -1 invalid, -3 wrong sequence.
  int push(int lane,uint64_t g,uint64_t seq,const char* data,size_t n) {
    std::lock_guard<std::mutex> lock(mutex_);
    if(lane!=0&&lane!=2)return -1;
    if(!current(g))return 0;
    if(!n||!data)return -1;
    if(seq!=next_[lane])return -3;
    if(n>cap_||bytes_[lane]+n>cap_||queues_[lane].size()>=items_){++pressure_;return 2;}
    queues_[lane].push_back({seq,std::string(data,n),0});bytes_[lane]+=n;++next_[lane];return 1;
  }
  int append(uint64_t g,const char* data,size_t n,bool finish) {
    std::lock_guard<std::mutex> lock(mutex_);
    if(!current(g))return 0;
    if(n&&!data)return -1;
    if(n>cap_||pending_.size()+bytes_[1]+n>cap_){++pressure_;return 2;}
    std::string candidate=pending_;if(n)candidate.append(data,n);
    size_t complete=0;
    if(!utf8(candidate,incremental_?valid_:0,complete)||(finish&&complete!=candidate.size()))return -1;
    size_t consumed=0;std::vector<std::string> segments;
    for(size_t i=incremental_?scan_:0;i<complete;) {
      ++scanned_;size_t delimiter=0;
      unsigned char c=candidate[i];
      if(c=='.'||c=='!'||c=='?'||c=='\n')delimiter=1;
      // UTF-8 Chinese full stop / fullwidth exclamation and question mark.
      if((c==0xe3||c==0xef)&&i+3<=complete&&(candidate.compare(i,3,"。")==0||candidate.compare(i,3,"！")==0||candidate.compare(i,3,"？")==0))delimiter=3;
      if(delimiter){i+=delimiter;segments.push_back(candidate.substr(consumed,i-consumed));consumed=i;}
      else ++i;
    }
    if(finish&&consumed<candidate.size()){segments.push_back(candidate.substr(consumed));consumed=candidate.size();}
    if(queues_[1].size()+segments.size()>items_){++pressure_;return 2;}
    for(auto& text:segments){bytes_[1]+=text.size();queues_[1].push_back({next_[1]++,std::move(text),0});}
    pending_=candidate.substr(consumed);scan_=complete-consumed;valid_=complete-consumed;
    return 1;
  }
  int pop(int lane,char* out,size_t cap,size_t& size,uint64_t& seq,uint64_t& generation) {
    std::lock_guard<std::mutex> lock(mutex_);
    if(lane<0||lane>2)return -1;
    if(queues_[lane].empty()){size=0;return 0;}
    auto& f=queues_[lane].front();size=f.data.size()-f.offset;
    if(cap<size)return -2;
    if(size&&!out)return -1;
    std::memcpy(out,f.data.data()+f.offset,size);seq=f.sequence;generation=generation_;
    bytes_[lane]-=size;queues_[lane].pop_front();return 1;
  }
  size_t render(uint64_t g,char* out,size_t n) {
    std::lock_guard<std::mutex> lock(mutex_);
    if(!out)return 0;
    std::memset(out,0,n);if(!current(g))return 0;
    size_t written=0;
    while(written<n&&!queues_[2].empty()) {
      auto& f=queues_[2].front();size_t take=std::min(n-written,f.data.size()-f.offset);
      std::memcpy(out+written,f.data.data()+f.offset,take);f.offset+=take;written+=take;bytes_[2]-=take;
      if(f.offset==f.data.size())queues_[2].pop_front();
    }
    rendered_+=written;return written;
  }
  uint64_t stat(int i) {
    std::lock_guard<std::mutex> lock(mutex_);
    if(i==0)return generation_;
    if(i>=1&&i<=3)return bytes_[i-1];
    if(i>=4&&i<=6)return queues_[i-4].size();
    if(i==7)return pending_.size();if(i==8)return stale_;if(i==9)return pressure_;
    if(i==10)return scanned_;if(i==11)return rendered_;return 0;
  }
};
}
