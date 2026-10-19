// Windows first-run UI. Preparation and game data remain local to the player's PC.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Web.Script.Serialization;
using System.Windows.Forms;

class Launcher : Form {
    readonly string root = AppDomain.CurrentDomain.BaseDirectory;
    readonly JavaScriptSerializer json = new JavaScriptSerializer();
    readonly TextBox cue = new TextBox(), work = new TextBox();
    readonly Button selectDisc = new Button(), selectWork = new Button(), prepare = new Button(), play = new Button(), cancel = new Button(), controller = new Button(), import = new Button(), openFolder = new Button();
    readonly Label state = new Label();
    readonly ProgressBar progress = new ProgressBar();
    Process worker, game;
    string settingsPath, packageId;
    bool busy;
    bool cancelled;
    string lastError;
    string smokePlayRoot;

    static string Quote(string value) {
        StringBuilder b = new StringBuilder("\""); int slashes = 0;
        foreach(char ch in value) {
            if(ch == '\\') {++slashes; continue;}
            if(ch == '"') {b.Append('\\',slashes*2+1); b.Append('"');}
            else {b.Append('\\',slashes); b.Append(ch);}
            slashes=0;
        }
        b.Append('\\',slashes*2); return b.Append('"').ToString();
    }
    static string Hash(string path) {
        using(var f=File.OpenRead(path)) using(var h=SHA256.Create()) return BitConverter.ToString(h.ComputeHash(f)).Replace("-","").ToLowerInvariant();
    }
    Dictionary<string,object> Read(string path) {return json.Deserialize<Dictionary<string,object>>(File.ReadAllText(path));}
    void Ui(Action action) {if(!IsDisposed && IsHandleCreated) BeginInvoke(action);}
    Label TextAt(string text,int x,int y,int width,int height) {
        var label=new Label {Text=text,Left=x,Top=y,Width=width,Height=height}; Controls.Add(label);return label;
    }
    void ButtonAt(Button button,string text,int x,int y,int width,EventHandler click) {
        button.Text=text;button.SetBounds(x,y,width,34);button.Click+=click;Controls.Add(button);
    }
    public Launcher(string testRoot) {
        Text="Shining Force III Native"; ClientSize=new Size(850,405);MinimumSize=Size;MaximumSize=Size;
        Font=new Font("Segoe UI",10);StartPosition=FormStartPosition.CenterScreen;FormBorderStyle=FormBorderStyle.FixedSingle;MaximizeBox=false;
        TextAt("Shining Force III Native",24,20,800,35).Font=new Font("Segoe UI",20,FontStyle.Bold);
        TextAt("Experimental alpha - Scenario 1 USA (unpatched V1.001)",25,65,790,25);
        TextAt("Choose your disc once. The app prepares it automatically, then you can play.\nNo compiler installation or commands needed. Your disc files stay on your PC.",25,99,790,48);
        TextAt("Disc CUE file",25,160,120,25);cue.SetBounds(155,157,535,28);Controls.Add(cue);
        ButtonAt(selectDisc,"Browse...",702,154,120,delegate {
            using(var d=new OpenFileDialog {Filter="Saturn disc cue (*.cue)|*.cue",Title="Choose your own Scenario 1 USA disc"}) if(d.ShowDialog(this)==DialogResult.OK) cue.Text=d.FileName;
        });
        TextAt("Game-data folder",25,206,125,25);work.SetBounds(155,203,535,28);Controls.Add(work);
        ButtonAt(selectWork,"Choose...",702,200,120,delegate {
            using(var d=new FolderBrowserDialog {Description="Choose a writable folder outside the application and source repositories",SelectedPath=work.Text}) if(d.ShowDialog(this)==DialogResult.OK) {work.Text=d.SelectedPath;RefreshReady();}
        });
        TextAt("First preparation can take several minutes and needs several GB of free space.",25,246,795,25);
        state.SetBounds(25,281,795,25);Controls.Add(state);progress.SetBounds(25,312,795,14);Controls.Add(progress);
        ButtonAt(prepare,"Prepare game",25,346,140,Prepare);
        ButtonAt(play,"Play",175,346,80,Play);
        ButtonAt(controller,"Controller setup",265,346,155,delegate {LaunchTool("controller-setup.exe","--setup");});
        ButtonAt(import,"Import saves",430,346,125,delegate {LaunchScript("import-saturn-save.ps1",true);});
        ButtonAt(openFolder,"Open data folder",565,346,145,delegate {if(Directory.Exists(work.Text)) Process.Start("explorer.exe",Quote(work.Text));});
        ButtonAt(cancel,"Cancel",720,346,100,delegate {CancelWorker();});
        settingsPath=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"SFIII Native","launcher.json");
        work.Text=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"SFIII Native","Game");
        if(testRoot!=null) {settingsPath=Path.Combine(testRoot,"launcher.json");work.Text=Path.Combine(testRoot,"Game");}
        try {var s=Read(settingsPath);cue.Text=(string)s["cue"];work.Text=(string)s["work"];} catch { }
        try {packageId=(string)Read(Path.Combine(root,"payload","package.json"))["build_id"];} catch {state.Text="Extract the complete application ZIP before running it.";prepare.Enabled=false;}
        cue.TextChanged+=delegate {if(!busy)RefreshReady();};
        work.TextChanged+=delegate {if(!busy)RefreshReady();};
        Shown+=delegate {RefreshReady();};
        FormClosing+=delegate(object sender,FormClosingEventArgs e) {
            if(busy && MessageBox.Show(this,"Cancel preparation and close? Existing saves will be kept.","Preparation is running",MessageBoxButtons.YesNo)!=DialogResult.Yes) {e.Cancel=true;return;}
            CancelWorker();
        };
    }
    void SaveSettings() {
        Directory.CreateDirectory(Path.GetDirectoryName(settingsPath));
        File.WriteAllText(settingsPath,json.Serialize(new Dictionary<string,object>{{"cue",cue.Text},{"work",work.Text}}));
    }
    bool Ready() {
        try {
            var prepared=Read(Path.Combine(work.Text,"desktop-ready.json"));
            string preparedCue=(string)prepared["cue"];
            if(String.IsNullOrWhiteSpace(cue.Text))cue.Text=preparedCue;
            if(!String.Equals(Path.GetFullPath(cue.Text),Path.GetFullPath(preparedCue),StringComparison.OrdinalIgnoreCase))return false;
            string selected=File.ReadAllText(Path.Combine(work.Text,"native-build.txt")).Trim();
            if(selected!="build-desktop-"+packageId || (string)prepared["build_id"]!=packageId)return false;
            string exe=Path.Combine(work.Text,selected,"saturn.exe");
            return File.Exists(preparedCue) && Hash(exe)==(string)prepared["executable_sha256"];
        } catch {return false;}
    }
    void RefreshReady() {
        if(busy)return;
        bool ready=Ready(),playing=game!=null;
        play.Enabled=ready && !playing;controller.Enabled=ready && !playing;import.Enabled=ready && !playing;
        prepare.Enabled=packageId!=null && !playing;selectDisc.Enabled=selectWork.Enabled=cue.Enabled=work.Enabled=!playing;
        cancel.Enabled=false;
        state.Text=packageId==null ? "Extract the complete application ZIP before running it." : playing ? "Game running. Close the game to change setup or import saves." : ready ? "Ready to play." : "Select your CUE file and click Prepare game.";
    }
    void SetBusy(bool value) {
        busy=value;prepare.Enabled=play.Enabled=controller.Enabled=import.Enabled=selectDisc.Enabled=selectWork.Enabled=cue.Enabled=work.Enabled=!value;
        cancel.Enabled=value;progress.Style=value ? ProgressBarStyle.Marquee : ProgressBarStyle.Continuous;progress.Value=0;
        if(!value)RefreshReady();
    }
    void Prepare(object sender,EventArgs e) {
        if(!File.Exists(cue.Text)) {MessageBox.Show(this,"Choose the CUE file beside your disc tracks first.");return;}
        try {
            work.Text=Path.GetFullPath(work.Text);cue.Text=Path.GetFullPath(cue.Text);SaveSettings();
            cancelled=false;lastError=null;
            string python=Path.Combine(root,"payload","python","python.exe"),script=Path.Combine(root,"payload","app","desktop","prepare.py");
            worker=new Process {StartInfo=new ProcessStartInfo(python,"-X utf8 -B "+Quote(script)+" --cue "+Quote(cue.Text)+" --work "+Quote(work.Text)) {UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true,RedirectStandardError=true},EnableRaisingEvents=true};
            worker.OutputDataReceived+=delegate(object s,DataReceivedEventArgs output) {
                if(output.Data==null || !output.Data.StartsWith("SF3_STATUS "))return;
                try {var data=json.Deserialize<Dictionary<string,object>>(output.Data.Substring(11));Ui(delegate {
                    state.Text=(string)data["message"];if((string)data["phase"]=="error")lastError=state.Text;
                    int total=Convert.ToInt32(data["total"]),done=Convert.ToInt32(data["done"]);
                    if(total>0) {progress.Style=ProgressBarStyle.Continuous;progress.Maximum=total;progress.Value=Math.Min(total,done);}
                });} catch { }
            };
            worker.ErrorDataReceived+=delegate(object s,DataReceivedEventArgs output) {if(output.Data!=null)Ui(delegate {state.Text="Preparation stopped. See the setup log in your game-data folder.";});};
            worker.Exited+=delegate {worker.WaitForExit();int code=worker.ExitCode;Ui(delegate {
                SetBusy(false);if(cancelled)state.Text="Preparation cancelled. Your saves were kept; you can retry.";
                else if(code!=0) {state.Text="Preparation did not finish. Your saves were kept.";MessageBox.Show(this,lastError ?? "Preparation did not finish. Check available disk space and the setup log under preparation in your game-data folder.","Preparation stopped");}
            });};
            SetBusy(true);state.Text="Starting preparation...";worker.Start();worker.BeginOutputReadLine();worker.BeginErrorReadLine();
        } catch(Exception error) {SetBusy(false);MessageBox.Show(this,error.Message,"Could not start preparation");}
    }
    void CancelWorker() {
        if(worker==null)return;
        try {if(!worker.HasExited) {
            cancelled=true;
            var start=new ProcessStartInfo(Path.Combine(Environment.SystemDirectory,"taskkill.exe"),"/PID "+worker.Id+" /T /F") {UseShellExecute=false,CreateNoWindow=true};
            using(var killer=Process.Start(start)) killer.WaitForExit();
        }} catch { }
    }
    void Play(object sender,EventArgs e) {
        try {
            if(!Ready()) {RefreshReady();return;}
            SaveSettings();File.WriteAllText(Path.Combine(work.Text,"save-import-python.txt"),Path.Combine(root,"payload","python","python.exe"));
            var start=ScriptStart("run-native.ps1",false);
            if(smokePlayRoot!=null)start.Arguments+=" -Headless -VBlanks 1800";
            start.RedirectStandardOutput=true;start.RedirectStandardError=true;
            var launchLog=new StreamWriter(Path.Combine(work.Text,"desktop-launch.log"),false,Encoding.UTF8) {AutoFlush=true};
            launchLog.WriteLine(start.FileName+" "+start.Arguments);
            game=new Process {StartInfo=start,EnableRaisingEvents=true};
            game.OutputDataReceived+=delegate(object s,DataReceivedEventArgs output) {if(output.Data!=null)lock(launchLog)launchLog.WriteLine(output.Data);};
            game.ErrorDataReceived+=delegate(object s,DataReceivedEventArgs output) {if(output.Data!=null)lock(launchLog)launchLog.WriteLine(output.Data);};
            game.Exited+=delegate {game.WaitForExit();int code=game.ExitCode;launchLog.Dispose();Ui(delegate {
                game.Dispose();game=null;RefreshReady();
                if(code!=0)state.Text="Game stopped with an error. See desktop-launch.log in your data folder.";
                if(smokePlayRoot!=null) {File.WriteAllText(Path.Combine(smokePlayRoot,code==0 ? "play-passed.txt" : "play-failed.txt"),"Play launcher exit: "+code);Environment.ExitCode=code;Close();}
            });};game.Start();game.BeginOutputReadLine();game.BeginErrorReadLine();RefreshReady();
        } catch(Exception error) {game=null;RefreshReady();MessageBox.Show(this,error.Message,"Could not launch game");}
    }
    ProcessStartInfo ScriptStart(string name,bool sta) {
        string powershell=Path.Combine(Environment.SystemDirectory,"WindowsPowerShell","v1.0","powershell.exe");
        var start=new ProcessStartInfo(powershell,"-NoProfile -ExecutionPolicy Bypass "+(sta ? "-STA " : "")+"-File "+Quote(Path.Combine(work.Text,name))+" -Work "+Quote(work.Text)) {UseShellExecute=false,CreateNoWindow=true,WorkingDirectory=work.Text};
        start.EnvironmentVariables["PSModulePath"]=Path.Combine(Environment.SystemDirectory,"WindowsPowerShell","v1.0","Modules");
        return start;
    }
    void LaunchScript(string name,bool sta) {try {Process.Start(ScriptStart(name,sta));} catch(Exception e) {MessageBox.Show(this,e.Message);}}
    void LaunchTool(string name,string args) {try {Process.Start(new ProcessStartInfo(Path.Combine(work.Text,name),args) {UseShellExecute=false,WorkingDirectory=work.Text});} catch(Exception e) {MessageBox.Show(this,e.Message);}}
    [STAThread] static void Main(string[] args) {
        Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);
        string testRoot=args.Length==2 && (args[0]=="--self-test" || args[0]=="--self-test-ready") ? Path.GetFullPath(args[1]) : null;
        var form=new Launcher(testRoot);
        if(testRoot!=null && args[0]=="--self-test-ready") {
            form.work.Text=testRoot;form.smokePlayRoot=testRoot;
            form.Shown+=delegate {
                form.RefreshReady();
                if(!form.Ready() || !form.play.Enabled || !form.controller.Enabled || !form.import.Enabled) {File.WriteAllText(Path.Combine(testRoot,"play-failed.txt"),"Prepared controls are not ready");Environment.ExitCode=1;form.Close();return;}
                using(var image=new Bitmap(form.Width,form.Height)) {form.DrawToBitmap(image,new Rectangle(Point.Empty,form.Size));image.Save(Path.Combine(testRoot,"ready-launcher.png"));}
                form.Play(null,EventArgs.Empty);
            };
            Application.Run(form);return;
        }
        if(testRoot!=null) form.Shown+=delegate {
            try {
                Directory.CreateDirectory(testRoot);form.SetBusy(true);
                if(form.prepare.Enabled || form.play.Enabled || !form.cancel.Enabled)throw new Exception("Busy controls are invalid");
                form.SetBusy(false);if(form.play.Enabled)throw new Exception("Unprepared installation must not be playable");
                using(var image=new Bitmap(form.Width,form.Height)) {form.DrawToBitmap(image,new Rectangle(Point.Empty,form.Size));image.Save(Path.Combine(testRoot,"launcher.png"));}
                form.SaveSettings();File.WriteAllText(Path.Combine(testRoot,"passed.txt"),"PASS: first-run state, busy/cancel controls, settings and UI rendering");
            } catch(Exception error) {File.WriteAllText(Path.Combine(testRoot,"failed.txt"),error.ToString());Environment.ExitCode=1;}
            form.Close();
        };
        Application.Run(form);
    }
}
