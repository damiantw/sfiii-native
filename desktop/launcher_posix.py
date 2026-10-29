"""Portable Tk desktop launcher. Game generation and progress remain on this PC."""
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

sys.dont_write_bytecode = True
from prepare_posix import APP, PAYLOAD, common, lock, package_root
from run_posix import selected_build
from ai_packs import install_selection, detach_selection
import shared_saves
from disc_profile import canonical_profile_id

# Accepted disc revision profiles (profiles/*.json ids) per game slot; the first is the recommended disc.
PROFILES = (('scenario1-translation-v25_1-addons', 'scenario1-usa-v1_001', 'scenario1-translation-v25_1'),
            ('scenario2-translation-v25_1-addons-v2_000', 'scenario2-translation-v25_1-addons-v1_003', 'scenario2-translation-v25_1-v2_000', 'scenario2-translation-v25_1-v1_003', 'scenario2-translation-v25_1-upgrade', 'scenario2-supplied-v1003', 'scenario2-translation-v24'),
            ('scenario3-translation-v25_1-addons-redump', 'scenario3-translation-v25_1-redump', 'scenario3-translation-v25_1'),
            ('premium-disc-translation-v25_1',))
# Default data folders keep their original names so existing game data stays where it was.
DATA_FOLDERS = ('Scenario1-USA', 'Scenario2-v24', 'Scenario3-v25_1', 'Premium-Disc-v25_1')

def data_root():
    if sys.platform == 'darwin':
        return Path.home()/'Library/Application Support/SFIII Native'
    return Path(os.environ.get('XDG_DATA_HOME',Path.home()/'.local/share'))/'SFIII Native'


class Launcher:
    def __init__(self, root, config=None):
        self.root, self.process = root, None
        self.events = queue.Queue()
        self.config = Path(config) if config else data_root()/'launcher.json'
        self.preferences = dict(selected=0,games={},separate_saves=False)
        if self.config.is_file():
            self.preferences.update(json.loads(self.config.read_text()))
        root.title('Shining Force III Native')
        root.geometry('850x490')
        root.minsize(740,450)
        frame = ttk.Frame(root,padding=20)
        frame.pack(fill='both',expand=True)
        frame.columnconfigure(1,weight=1)
        ttk.Label(frame,text='Shining Force III Native',font=('',22,'bold')).grid(row=0,column=0,columnspan=3,sticky='w',pady=(0,18))
        self.selection = ttk.Combobox(frame,state='readonly',values=['Scenario 1 USA (V1.001 or Translation Project V25.1)','Scenario 2 Translation Project V25.1 / V25 / v24 (experimental)','Scenario 3 Translation Project V25.1 (experimental)','Premium Disc Translation Project V25.1 (experimental)'])
        self.selection.grid(row=1,column=1,sticky='ew',pady=5)
        ttk.Label(frame,text='Game').grid(row=1,column=0,sticky='w',padx=(0,12))
        self.cue, self.work = tk.StringVar(), tk.StringVar()
        self.entries=[]
        for row,title,var,browse in [(2,'Disc (CUE / CHD)',self.cue,self.browse_disc),(3,'Game-data folder',self.work,self.browse_work)]:
            ttk.Label(frame,text=title).grid(row=row,column=0,sticky='w',padx=(0,12))
            entry=ttk.Entry(frame,textvariable=var)
            entry.grid(row=row,column=1,sticky='ew',pady=5)
            button=ttk.Button(frame,text='Browse',command=browse)
            button.grid(row=row,column=2,padx=(10,0))
            self.entries.extend([entry,button])
        bar=ttk.Frame(frame)
        bar.grid(row=4,column=0,columnspan=3,sticky='w',pady=15)
        self.prepare=ttk.Button(bar,text='Prepare game',command=self.prepare_game)
        self.play=ttk.Button(bar,text='Play',command=self.play_game)
        self.controller=ttk.Button(bar,text='Controller setup',command=lambda:self.controller_tool('--setup'))
        self.test=ttk.Button(bar,text='Test controller',command=lambda:self.controller_tool('--test'))
        self.import_button=ttk.Button(bar,text='Save manager',command=self.import_saves)
        self.cancel=ttk.Button(bar,text='Cancel setup',command=self.cancel_setup)
        for button in [self.prepare,self.play,self.controller,self.test,self.import_button,self.cancel]:button.pack(side='left',padx=(0,7))
        artwork=ttk.Frame(frame)
        artwork.grid(row=5,column=0,columnspan=3,sticky='w')
        self.artwork=ttk.Button(artwork,text='Attach optional graphics',command=self.attach_artwork)
        self.artwork.pack(side='left',padx=(0,7))
        self.original_art=ttk.Button(artwork,text='Use original graphics',command=self.detach_artwork)
        self.original_art.pack(side='left')
        # One backup memory for every scenario (like one Saturn), so each game's own new-game
        # import finds the previous scenario's COMPLETE record. Opt out to keep one file per game.
        self.separate=tk.BooleanVar(value=bool(self.preferences.get('separate_saves',False)))
        self.separate_box=ttk.Checkbutton(artwork,text='Separate saves per scenario (no automatic transfer)',variable=self.separate,command=self.remember)
        self.separate_box.pack(side='left',padx=(14,0))
        self.saves_note=''
        self.state=tk.StringVar(value='Choose your supported disc, then prepare the game.')
        ttk.Label(frame,textvariable=self.state,wraplength=780).grid(row=6,column=0,columnspan=3,sticky='w',pady=5)
        self.progress=ttk.Progressbar(frame,mode='indeterminate')
        self.progress.grid(row=7,column=0,columnspan=3,sticky='ew',pady=10)
        ttk.Label(frame,text='Experimental Linux/macOS preview. Keep a backup of your game-data folder.\nNo game assets or BIOS included. Setup and compilation run locally with bundled tools.',wraplength=780).grid(row=8,column=0,columnspan=3,sticky='w')
        self.active=max(0,min(len(PROFILES)-1,int(self.preferences.get('selected',0))))
        self.selection.current(self.active)
        self.restore()
        self.selection.bind('<<ComboboxSelected>>',self.change_game)
        root.protocol('WM_DELETE_WINDOW',self.close)
        root.after(100,self.poll)

    def remember(self):
        self.preferences['selected']=self.active
        if hasattr(self,'separate'):self.preferences['separate_saves']=bool(self.separate.get())
        self.preferences['games'][str(self.active)]=dict(cue=self.cue.get(),work=self.work.get())
        self.config.parent.mkdir(parents=True,exist_ok=True)
        common.atomic_json(self.config,self.preferences)

    def restore(self):
        values=self.preferences['games'].get(str(self.active),{})
        self.cue.set(values.get('cue',''))
        self.work.set(values.get('work',str(data_root()/DATA_FOLDERS[self.active])))
        self.refresh()

    def change_game(self,event=None):
        self.remember()
        self.active=self.selection.current()
        self.restore()
        self.remember()

    def ready(self):
        try:
            work=Path(self.work.get())
            ready=json.loads((work/'desktop-ready.json').read_text())
            package=json.loads((PAYLOAD/'package.json').read_text())
            return (ready['build_id']==package['build_id'] and canonical_profile_id(ready['profile_id']) in PROFILES[self.active]
                    and common.sha(selected_build(work)/'saturn')==ready['executable_sha256'])
        except (OSError,ValueError,KeyError):return False

    def refresh(self):
        busy=self.process is not None
        ready=not busy and self.ready()
        for button in [self.play,self.controller,self.test,self.import_button,self.artwork,self.original_art]:button.configure(state='normal' if ready else 'disabled')
        self.prepare.configure(state='disabled' if busy else 'normal')
        self.cancel.configure(state='normal' if busy and self.task=='prepare' else 'disabled')
        self.selection.configure(state='disabled' if busy else 'readonly')
        for widget in self.entries:widget.configure(state='disabled' if busy else 'normal')
        if hasattr(self,'separate_box'):self.separate_box.configure(state='disabled' if busy else 'normal')

    def browse_disc(self):
        path=filedialog.askopenfilename(filetypes=[('Saturn images','*.cue *.CUE *.chd *.CHD'),('All files','*')])
        if path:self.cue.set(path)
        self.remember()
        self.refresh()

    def browse_work(self):
        path=filedialog.askdirectory()
        if path:self.work.set(path)
        self.remember()
        self.refresh()

    def start(self,args,task,env=None):
        self.remember()
        self.task=task
        self.state.set('Preparing...' if task=='prepare' else 'Running '+task+'. Close the game/tool window when finished.')
        self.process=subprocess.Popen(list(map(str,args)),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                                      text=True,encoding='utf-8',errors='replace',start_new_session=True,env=env)
        self.progress.start()
        self.refresh()
        def read(process):
            lines=[]
            for line in process.stdout:
                lines.append(line)
                if line.startswith('SF3_STATUS '):self.events.put(('status',line[11:]))
            self.events.put(('done',(process.wait(),''.join(lines))))
        threading.Thread(target=read,args=(self.process,),daemon=True).start()

    def prepare_game(self):
        self.start([PAYLOAD/'python/bin/python3','-X','utf8','-B',APP/'desktop/prepare_posix.py',
                    '--cue',self.cue.get(),'--work',self.work.get(),'--scenario',str(self.active+1)],'prepare')

    def play_args(self):
        args=[PAYLOAD/'python/bin/python3','-X','utf8','-B',APP/'desktop/run_posix.py','--work',self.work.get()]
        if self.separate.get():return args+['--separate-saves']
        args+=['--launcher-settings',self.config]
        for entry in self.preferences.get('games',{}).values():
            if isinstance(entry,dict) and entry.get('work'):args+=['--migrate-from',entry['work']]
        return args

    def play_game(self):
        self.saves_note=''
        self.start(self.play_args(),'game')

    def attach_artwork(self):
        report=filedialog.askopenfilename(title='Select locally generated packs-report.json',filetypes=[('Artwork pack report','*.json')])
        if not report:return
        try:
            with lock(Path(self.work.get())):
                install_selection(Path(report),Path(self.work.get()),APP/'profiles')
            self.state.set('Optional artwork attached. Select AI graphics in the game menu. Menus and unmatched artwork stay original.')
        except (OSError,ValueError,KeyError,TypeError) as error:
            messagebox.showerror('Could not attach artwork',str(error),parent=self.root)

    def detach_artwork(self):
        try:
            with lock(Path(self.work.get())):detach_selection(Path(self.work.get()))
            self.state.set('Original graphics selected. Previous artwork selection was preserved.')
        except (OSError,ValueError) as error:
            messagebox.showerror('Could not change artwork',str(error),parent=self.root)

    def controller_tool(self,mode):
        env={**os.environ,'SF3_CONTROLLER_DIR':self.work.get()}
        self.start([selected_build(Path(self.work.get()))/'controller_setup',mode],'controller',env)

    def import_saves(self):
        action=messagebox.askyesnocancel('Save manager','Export ordinary saves as BIN files?\nYes: Export for Saturn / Saroo editor\nNo: Import BIN / YSBAK saves',parent=self.root)
        if action is None:return
        if action:
            folder=filedialog.askdirectory(title='Choose export location')
            if not folder:return
            device='cartridge' if messagebox.askyesno('Save storage','Export from cartridge memory?\nNo selects internal memory.',parent=self.root) else 'internal'
            try:
                import importlib.util,time
                spec=importlib.util.spec_from_file_location('sf3_import',APP/'tools/import-saturn-save.py')
                module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
                work=common.external_work(Path(self.work.get()),package_root())
                destination=Path(folder)/('SFIII-save-export-'+str(time.time_ns()))
                if self.separate.get():
                    with lock(work):module.export_files(work/'experimental-backup.bin',device,destination)
                else:
                    shared=shared_saves.default_dir()
                    with lock(work),shared_saves.lock(shared):
                        # Merge the per-scenario files first, so the export includes every scenario's saves.
                        shared_saves.prepare_session(work,shared,[self.config],self.known_works())
                        module.export_files(shared/shared_saves.SAVE_NAME,device,destination)
                messagebox.showinfo('Export complete','BIN saves exported to '+str(destination),parent=self.root)
            except Exception as e:messagebox.showerror('Could not export',str(e),parent=self.root)
            return
        paths=filedialog.askopenfilenames(filetypes=[('Saturn saves','*.BIN *.bin *.ysbak'),('All files','*')])
        if not paths:return
        dialog=tk.Toplevel(self.root)
        dialog.title('Import Saturn saves')
        ttk.Label(dialog,text='Destination storage (existing data is backed up)').pack(padx=20,pady=10)
        choice=ttk.Combobox(dialog,state='readonly',values=['cartridge','internal'])
        choice.current(0)
        choice.pack(padx=20,pady=10)
        replace=tk.BooleanVar(value=False)
        ttk.Checkbutton(dialog,text='Replace matching save names (backup retained)',variable=replace).pack(padx=20,pady=10)
        def apply():
            try:
                import importlib.util
                spec=importlib.util.spec_from_file_location('sf3_import',APP/'tools/import-saturn-save.py')
                module=importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                work=common.external_work(Path(self.work.get()),package_root())
                if self.separate.get():
                    with lock(work):module.import_files(work/'experimental-backup.bin',choice.get(),list(map(Path,paths)),replace.get())
                    self.state.set('Saves imported. Use the game’s own Load menu.')
                else:
                    shared=shared_saves.default_dir()
                    with lock(work),shared_saves.lock(shared):
                        # Merge the per-scenario files first, so an import never shadows an unmerged save.
                        shared_saves.prepare_session(work,shared,[self.config],self.known_works())
                        module.import_files(shared/shared_saves.SAVE_NAME,choice.get(),list(map(Path,paths)),replace.get())
                    self.state.set('Saves imported into the backup memory shared by all scenarios. Use the game’s own Load menu.')
                dialog.destroy()
            except Exception as e:messagebox.showerror('Could not import',str(e),parent=dialog)
        ttk.Button(dialog,text='Import',command=apply).pack(padx=20,pady=15)

    def known_works(self):
        return [Path(e['work']) for e in self.preferences.get('games',{}).values() if isinstance(e,dict) and e.get('work')]

    def cancel_setup(self):
        if self.process and self.task=='prepare':
            os.killpg(self.process.pid,signal.SIGTERM)
            self.state.set('Setup cancelled; previous builds and ordinary saves are retained.')

    def poll(self):
        while not self.events.empty():
            event,data=self.events.get()
            if event=='status':
                status=json.loads(data)
                self.state.set(status['message'])
                if status.get('phase')=='saves':
                    self.saves_note=(self.saves_note+' '+status['message']).strip()
                    if 'full' in status['message'] or 'WARNING' in status['message']:
                        messagebox.showwarning('Shared backup memory',status['message'],parent=self.root)
            else:
                code,text=data
                self.process=None
                self.progress.stop()
                self.state.set(('Ready. '+self.saves_note).strip() if code==0 else text[-800:] or 'Stopped; inspect the local session/setup log.')
                self.refresh()
        self.root.after(100,self.poll)

    def close(self):
        if self.process:
            messagebox.showinfo('Still running','Close the game/tool window or cancel setup before closing the launcher.')
        else:
            self.remember()
            self.root.destroy()


if __name__=='__main__':
    root=tk.Tk()
    if len(sys.argv)==3 and sys.argv[1]=='--self-test':
        ui=Launcher(root,Path(sys.argv[2])/'launcher.json')
        root.update()
        assert str(ui.play['state'])=='disabled'
        ui.cue.set('/synthetic/one.cue')
        ui.work.set('/synthetic/one')
        ui.selection.current(1)
        ui.change_game()
        assert ui.cue.get()=='' and ui.work.get()!='/synthetic/one'
        ui.selection.current(0)
        ui.change_game()
        assert ui.cue.get()=='/synthetic/one.cue'
        ui.close()
    else:
        Launcher(root)
        root.mainloop()
