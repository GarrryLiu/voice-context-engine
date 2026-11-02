#include "runtime.hpp"
extern "C" {
void* vr_create(size_t bytes,size_t items,int incremental) noexcept {
  try {if(!bytes||!items)return nullptr;return new voice::Runtime(bytes,items,incremental!=0);}catch(...){return nullptr;}
}
void vr_destroy(void* p) noexcept {delete static_cast<voice::Runtime*>(p);}
int vr_advance(void* p,uint64_t generation) noexcept {try{return p?static_cast<voice::Runtime*>(p)->advance(generation):-1;}catch(...){return -1;}}
int vr_push(void* p,int lane,uint64_t g,uint64_t seq,const char* data,size_t n) noexcept {
  try{return p?static_cast<voice::Runtime*>(p)->push(lane,g,seq,data,n):-1;}catch(...){return -1;}
}
int vr_append(void* p,uint64_t g,const char* data,size_t n,int finish) noexcept {
  try{return p?static_cast<voice::Runtime*>(p)->append(g,data,n,finish!=0):-1;}catch(...){return -1;}
}
int vr_pop(void* p,int lane,char* out,size_t cap,size_t* size,uint64_t* seq,uint64_t* generation) noexcept {
  try {if(!p||!size||!seq||!generation)return -1;return static_cast<voice::Runtime*>(p)->pop(lane,out,cap,*size,*seq,*generation);}catch(...){return -1;}
}
size_t vr_render(void* p,uint64_t g,char* out,size_t n) noexcept {
  try{return p?static_cast<voice::Runtime*>(p)->render(g,out,n):0;}catch(...){return 0;}
}
uint64_t vr_stat(void* p,int i) noexcept {return p?static_cast<voice::Runtime*>(p)->stat(i):0;}
}
