// Locate the portable Python/launcher relative to this executable, after moving the app.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#ifdef __APPLE__
extern int _NSGetExecutablePath(char *, uint32_t *);
#endif

int main(int argc,char **argv) {
    char executable[4096],resolved[4096],python[4096],script[4096];
#ifdef __APPLE__
    uint32_t size=sizeof executable;
    if(_NSGetExecutablePath(executable,&size))return 1;
#else
    ssize_t size=readlink("/proc/self/exe",executable,sizeof executable-1);
    if(size<0)return 1;
    executable[size]=0;
#endif
    if(!realpath(executable,resolved))return 1;
    char *slash=strrchr(resolved,'/');
    if(!slash)return 1;
    *slash=0;
#ifdef __APPLE__
    const char *relative="/../Resources/payload";
#else
    const char *relative="/payload";
#endif
    if(snprintf(python,sizeof python,"%s%s/python/bin/python3",resolved,relative)>=(int)sizeof python)return 1;
    if(snprintf(script,sizeof script,"%s%s/app/desktop/launcher_posix.py",resolved,relative)>=(int)sizeof script)return 1;
    char **args=calloc((size_t)argc+6,sizeof(char*));
    if(!args)return 1;
    args[0]=python;args[1]="-X";args[2]="utf8";args[3]="-B";args[4]=script;
    for(int i=1;i<argc;++i)args[4+i]=argv[i];
    execv(python,args);
    perror("Could not open the bundled launcher");
    free(args);
    return 1;
}
