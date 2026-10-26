// Exact native ownership and composition, with HD projection/sampling on the GPU.
// SDL reserves sampled texture slot 0 for the draw's white texture.
ByteAddressBuffer scene : register(t1, space2);
ByteAddressBuffer art : register(t2, space2);
uint S(uint index) {return scene.Load(index*4);}
uint A(uint index) {return art.Load(index*4);}
// SDL's distributed DXIL vertex shader uses TEXCOORD0/1 for color/UV.
struct Input {float4 color:TEXCOORD0;float2 uv:TEXCOORD1;float4 position:SV_Position;};
uint blend(uint a,uint b,uint w) {
    uint t=256-w;
    return ((((a&0xFF00FF)*t+(b&0xFF00FF)*w)>>8)&0xFF00FF)
        | (((((a>>8)&0xFF00FF)*t+((b>>8)&0xFF00FF)*w)>>8)&0xFF00FF)<<8;
}
float4 main(Input input):SV_Target {
    uint w=S(0),h=S(1);
    uint2 pixel=uint2(input.position.xy);
    precise float2 position=(float2(pixel)+0.5)*float2(w,h)/float2(1440,1080)-0.5;
    int2 cell=min((2*pixel+1)*uint2(w,h)/uint2(2880,2160),uint2(w-1,h-1));
    uint p=4+(cell.y*w+cell.x)*8,id=S(p);
    if(id==0 || id>S(3)) return 0;
    uint q=S(2)+(id-1)*32,base=S(q+22);
    if(base==0xFFFFFFFF) return 0;
    float2 a=asfloat(uint2(S(q),S(q+1))),b=asfloat(uint2(S(q+2),S(q+3)))-a;
    float2 d=asfloat(uint2(S(q+6),S(q+7)))-a;
    float2 cross=a-asfloat(uint2(S(q+2),S(q+3)))+asfloat(uint2(S(q+4),S(q+5)))-asfloat(uint2(S(q+6),S(q+7)));
    precise float2 uv=0.5;
    [unroll] for(int i=0;i<5;++i) {
        float2 f=a+b*uv.x+d*uv.y+cross*uv.x*uv.y-float2(cell);
        float2 du=b+cross*uv.y,dv=d+cross*uv.x;
        float det=du.x*dv.y-du.y*dv.x;if(abs(det)<0.00001) return 0;
        uv-=float2(f.x*dv.y-f.y*dv.x,du.x*f.y-du.y*f.x)/det;
    }
    if(any(isnan(uv)) || any(isinf(uv))) return 0;
    uv=saturate(uv);
    float2 du=b+cross*uv.y,dv=d+cross*uv.x;
    float det=du.x*dv.y-du.y*dv.x;if(abs(det)<0.00001) return 0;
    float2 delta=position-float2(cell);
    float2 shift=float2(dv.y*delta.x-dv.x*delta.y,-du.y*delta.x+du.x*delta.y)/det;
    float2 sign=float2(S(q+20)!=0?-1:1,S(q+21)!=0?-1:1);
    uv=saturate((uv-0.5)*sign+0.5+shift*sign);
    uint tw=S(q+23),th=S(q+24);
    float2 lo=asfloat(uint2(S(q+25),S(q+26))),hi=asfloat(uint2(S(q+27),S(q+28)));
    precise float2 tex=(lo+uv*(hi-lo))*float2(tw-1,th-1);
    uint2 t=uint2(tex),s=min(t+1,uint2(tw-1,th-1)),fraction=uint2(frac(tex)*256);
    uint rgba=blend(blend(A(base+t.y*tw+t.x),A(base+t.y*tw+s.x),fraction.x),blend(A(base+s.y*tw+t.x),A(base+s.y*tw+s.x),fraction.x),fraction.y);
    float2 guv=(uv-0.5)*sign+0.5;uint color=0;
    [unroll] for(int ch=0;ch<3;++ch) {
        int sh=16-ch*8;
        float upper=lerp(asfloat(S(q+8+ch)),asfloat(S(q+11+ch)),guv.x);
        float lower=lerp(asfloat(S(q+17+ch)),asfloat(S(q+14+ch)),guv.x);
        uint c=uint(clamp(int(float((rgba>>sh)&255)+lerp(upper,lower,guv.y)+0.5),0,255));
        uint flags=S(p+6),second=(S(p+1)>>sh)&255,ratio=S(p+5);
        if(flags&1) c=(flags&2)?min(c+second,255):((c*(31-ratio)+second*(ratio+1))>>5);
        c=uint(clamp(int(c)+int(S(p+2+ch)),0,255));if(flags&4) c>>=1;
        color|=c<<sh;
    }
    return float4(float3((color>>16)&255,(color>>8)&255,color&255)/255.0,float(rgba>>24)/255.0);
}
