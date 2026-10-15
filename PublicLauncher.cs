using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Windows.Forms;

// Portable launcher. Runtime and app source are embedded resources, not downloads.
internal class PublicLauncher {
    private const string BuildId = "BUILD_ID_PLACEHOLDER";
    [STAThread] private static int Main(string[] args) {
        try {
            string cacheParent = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "OverTheHillProfileManager", "Runtime");
            List<string> forwarded = new List<string>();
            bool diagnostic = false;
            for (int i=0; i<args.Length; i++) {
                if (args[i] == "--runtime-cache") {
                    if (++i >= args.Length) throw new ArgumentException("Missing runtime cache directory.");
                    cacheParent = Path.GetFullPath(args[i]);
                } else { forwarded.Add(args[i]); if (args[i] == "--smoke-test") diagnostic=true; }
            }
            Directory.CreateDirectory(cacheParent);
            RejectRedirects(cacheParent);
            string runtime = Path.Combine(cacheParent, BuildId);
            Dictionary<string,string> manifest = ReadManifest();
            using (Mutex mutex = new Mutex(false, "Local\\OverTheHillProfileManager_"+BuildId)) {
                bool held=false;
                try {
                    try { held=mutex.WaitOne(60000); } catch(AbandonedMutexException) { held=true; }
                    if (!held) throw new IOException("Another copy is preparing the app. Please try again.");
                    if (!ValidRuntime(runtime, manifest)) {
                        string stage=Path.Combine(cacheParent, "stage-"+Guid.NewGuid().ToString("N"));
                        Directory.CreateDirectory(stage);
                        using(Stream payload=Assembly.GetExecutingAssembly().GetManifestResourceStream("RuntimePayload"))
                        using(ZipArchive archive=new ZipArchive(payload,ZipArchiveMode.Read)) {
                            foreach(ZipArchiveEntry entry in archive.Entries) {
                                string path=SafePath(stage,entry.FullName);
                                if(entry.FullName.EndsWith("/")) { Directory.CreateDirectory(path); continue; }
                                Directory.CreateDirectory(Path.GetDirectoryName(path));
                                using(Stream input=entry.Open()) using(FileStream output=new FileStream(path,FileMode.CreateNew,FileAccess.Write)) { input.CopyTo(output); }
                            }
                        }
                        if(!ValidRuntime(stage,manifest)) throw new IOException("The bundled files could not be verified.");
                        // Keep a damaged previous cache for inspection; never recursively delete user files.
                        if(Directory.Exists(runtime)) Directory.Move(runtime, runtime+".old-"+Guid.NewGuid().ToString("N"));
                        Directory.Move(stage,runtime);
                    }
                } finally { if(held) mutex.ReleaseMutex(); }
            }
            ProcessStartInfo info=new ProcessStartInfo(Path.Combine(runtime,diagnostic?"python.exe":"pythonw.exe"));
            List<string> command=new List<string>();
            command.Add(Path.Combine(runtime,"app","profile_manager.py")); command.AddRange(forwarded);
            info.Arguments=String.Join(" ",command.ConvertAll(Quote).ToArray());
            info.WorkingDirectory=Path.Combine(runtime,"app");
            info.UseShellExecute=false; info.CreateNoWindow=true;
            info.EnvironmentVariables["PYTHONDONTWRITEBYTECODE"]="1";
            info.EnvironmentVariables["TCL_LIBRARY"]=Path.Combine(runtime,"tcl","tcl8.6");
            info.EnvironmentVariables["TK_LIBRARY"]=Path.Combine(runtime,"tcl","tk8.6");
            info.EnvironmentVariables.Remove("PYTHONPATH"); info.EnvironmentVariables.Remove("PYTHONHOME");
            using(Process child=Process.Start(info)) { child.WaitForExit(); return child.ExitCode; }
        } catch(Exception ex) { MessageBox.Show(ex.Message,"Over the Hill Profile Manager",MessageBoxButtons.OK,MessageBoxIcon.Error); return 1; }
    }
    private static Dictionary<string,string> ReadManifest() {
        Dictionary<string,string> entries=new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase);
        using(Stream source=Assembly.GetExecutingAssembly().GetManifestResourceStream("PayloadManifest"))
        using(StreamReader reader=new StreamReader(source,Encoding.UTF8)) {
            string line; while((line=reader.ReadLine())!=null) { int split=line.IndexOf('\t'); if(split<1) throw new IOException("Invalid bundled manifest."); entries.Add(line.Substring(split+1),line.Substring(0,split)); }
        }
        return entries;
    }
    private static string SafePath(string root,string relative) {
        string path=Path.GetFullPath(Path.Combine(root,relative.Replace('/',Path.DirectorySeparatorChar)));
        if(Path.IsPathRooted(relative) || !path.StartsWith(Path.GetFullPath(root)+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase)) throw new IOException("Invalid bundled path.");
        return path;
    }
    private static void RejectRedirects(string path) {
        for(DirectoryInfo dir=new DirectoryInfo(path);dir!=null;dir=dir.Parent) {
            if((dir.Attributes&FileAttributes.ReparsePoint)!=0) throw new IOException("The runtime cache must use an ordinary local folder.");
        }
    }
    private static bool ValidRuntime(string root,Dictionary<string,string> manifest) {
        if(!Directory.Exists(root)) return false;
        RejectRedirects(root);
        // Walk without following junctions, and reject unrecognized files that could shadow imports.
        Queue<string> directories=new Queue<string>(); directories.Enqueue(root); int count=0;
        while(directories.Count>0) {
            string dir=directories.Dequeue();
            foreach(string child in Directory.GetDirectories(dir)) { if((File.GetAttributes(child)&FileAttributes.ReparsePoint)!=0) return false; directories.Enqueue(child); }
            foreach(string file in Directory.GetFiles(dir)) {
                if((File.GetAttributes(file)&FileAttributes.ReparsePoint)!=0) return false;
                string relative=file.Substring(root.Length+1).Replace(Path.DirectorySeparatorChar,'/');
                string expected; if(!manifest.TryGetValue(relative,out expected)) return false;
                using(SHA256 sha=SHA256.Create()) using(FileStream input=File.OpenRead(file)) {
                    string actual=BitConverter.ToString(sha.ComputeHash(input)).Replace("-","").ToLowerInvariant();
                    if(actual!=expected) return false;
                }
                count++;
            }
        }
        return count==manifest.Count;
    }
    private static string Quote(string value) {
        StringBuilder result=new StringBuilder("\""); int slashes=0;
        foreach(char c in value) {
            if(c=='\\') { slashes++; continue; }
            if(c=='\"') { result.Append('\\',slashes*2+1); result.Append(c); slashes=0; continue; }
            result.Append('\\',slashes); slashes=0; result.Append(c);
        }
        result.Append('\\',slashes*2); result.Append('"'); return result.ToString();
    }
}
