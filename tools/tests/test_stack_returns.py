"""Compile invented SH-2 callers and compare their returns with the ISA reference."""
import contextlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'.local/saturn-recomp/src'))


class StackReturns(unittest.TestCase):
    def image(self, variant):
        words = [0x0009]*64
        # Outer caller saves PR, invokes a wrapper, and writes a result afterward.
        words[:7] = [0x4F22,0xB00D,0x0009,0xE02A,0x4F26,0x000B,0x0009]
        words[16:24] = [0xD006,0x4F22,0x400B,0x0009,0x4F26,0xE107,0x000B,0x0009]
        words[30:32] = [0x0601,0x0040]
        # Zero selects the nonlocal return; nonzero returns to the wrapper.
        helper = [0x2448,0x8901,0x000B,0xE203,0x4F26,0x000B,0xE209]
        if variant == 'bad_sp':
            helper[4:] = [0x4F26,0x7F04,0x000B,0xE209]
        elif variant == 'bad_target':
            helper[4:] = [0x4F26,0xE000,0x402A,0x000B,0xE209]
        words[32:32+len(helper)] = helper
        return b''.join(w.to_bytes(2,'big') for w in words)

    def test_generated_normal_and_stack_pop_returns_match_reference_and_reject_corruption(self):
        compiler = os.environ.get('CXX') or shutil.which('c++') or shutil.which('clang++') or shutil.which('g++')
        if not compiler:
            self.skipTest('Native C++ compiler unavailable')
        from saturnrecomp.recomp.__main__ import generate
        from saturnrecomp.sh2emu import CPU, Memory
        base = 0x06010000
        expected = []
        for value in (0,1,0xFFFFFFFF):
            mem=Memory();mem.add(base,128,self.image('good'));mem.add(0x06070000,0x20000)
            cpu=CPU(mem);cpu.r[1]=0x1234;cpu.call(base,r4=value,r15=0x06080000)
            expected.append((value,cpu.r[0],cpu.r[1],cpu.r[2],cpu.r[15],cpu.pr,cpu.pc))
        with tempfile.TemporaryDirectory() as d:
            temp=Path(d);specs=[]
            for name,variant in [('GOOD','good'),('STRICT','good'),('BADSP','bad_sp'),('BADTARGET','bad_target')]:
                path=temp/(name+'.bin');path.write_bytes(self.image(variant))
                specs.append((name,str(path),base,[]))
            out=temp/'generated'
            with contextlib.redirect_stdout(io.StringIO()):
                generate(specs,str(out),runtime_literals={s[0] for s in specs},
                         stack_return_calls={name:{base+36} for name in ('GOOD','BADSP','BADTARGET')})
            (temp/'runner.cpp').write_text(r'''
#include "saturn/sh2.h"
#include <cstdio>
#include <fstream>
#include <iterator>
#include <vector>
#include <string>
extern const SH2Module* const g_sh2_modules[];
struct BadReturn {};
void sh2_bad_return(SH2Context&,uint32_t) {throw BadReturn{};}
void sh2_program_start(SH2Context&,uint32_t) {throw BadReturn{};}
void sh2_call_unknown(SH2Context&,uint32_t) {throw BadReturn{};}
uint32_t sh2_mmio_read(uint32_t,int) {return 0;}
void sh2_mmio_write(uint32_t,uint32_t,int) {}
void sh2_poll(SH2Context&) {}
void sh2_sleep(SH2Context&,uint32_t) {throw BadReturn{};}
void sh2_trapa(SH2Context&,uint32_t,uint32_t) {throw BadReturn{};}
int main(int argc,char** argv) {
 for(int module=0;module<4;++module) {
  const auto* image=g_sh2_modules[module];
  std::ifstream f(std::string(argv[1])+"/"+image->name+".bin",std::ios::binary);
  std::vector<uint8_t> bytes((std::istreambuf_iterator<char>(f)),{});
  if(bytes.size()!=128 || !sh2_mem_write(image->base,bytes.data(),bytes.size()))return 2;
  for(uint32_t value: {0u,1u,0xFFFFFFFFu}) {
   sh2_activate(image);SH2Context c{};c.pr=0xFFFFFFF0;c.r[15]=0x06080000;c.r[1]=0x1234;c.r[4]=value;c.budget=100000;
   bool bad=false;try {sh2_lookup(image->base)(c);}catch(const BadReturn&) {bad=true;}
   if(module==0) {
    if(bad)return 3;
    std::printf("%u %u %u %u %u %u %u\n",value,c.r[0],c.r[1],c.r[2],c.r[15],c.pr,c.pc);
   } else if(bad!=(value==0))return 4;
  }
 }
}
''')
            exe=temp/('check.exe' if os.name=='nt' else 'check')
            command=[compiler,'-std=c++20','-O1','-I'+str(ROOT/'.local/saturn-recomp/runtime/include'),
                     str(temp/'runner.cpp'),str(ROOT/'.local/saturn-recomp/runtime/src/core/core.cpp'),
                     *map(str,sorted(out.glob('*.cpp'))),'-o',str(exe)]
            if os.name=='nt':command.append('-static')
            build=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(build.returncode,0,build.stdout+build.stderr)
            result=subprocess.run([str(exe),str(temp)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            actual=[tuple(map(int,line.split())) for line in result.stdout.splitlines()]
            self.assertEqual(actual,expected)


if __name__=='__main__':unittest.main()
