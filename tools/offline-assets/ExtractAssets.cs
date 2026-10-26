// Read-only adapter to a separately supplied SF3Tools checkout. No game assets are bundled.
using System.Collections;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using CommonLib.Arrays;
using CommonLib.Imaging;
using CommonLib.NamedValues;
using SF3.ByteData;
using SF3.Models.Files;
using SF3.Models.Files.MPD;
using SF3.Models.Files.CHR;
using SF3.Models.Files.CHP;
using SF3.Models.Tables;
using SF3.NamedValues;
using SF3.Types;
using SF3.Utils;

internal static class ExtractAssets {
    static readonly JsonSerializerOptions Json = new() { WriteIndented = true };
    static string Hash(byte[] bytes) => Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();

    static int Main(string[] args) {
        if(args.Length != 4) { Console.Error.WriteLine("extract-assets SCENARIO FILE ASSET_STORE RECEIPT");return 2; }
        var input=Path.GetFullPath(args[1]);var store=Path.GetFullPath(args[2]);
        var receipt=Path.GetFullPath(args[3]);
        Directory.CreateDirectory(Path.GetDirectoryName(receipt)!);
        // SF3Lib resolves its supplied lookup resources relative to the process directory.
        Directory.SetCurrentDirectory(AppContext.BaseDirectory);
        var images=new List<object>();var warnings=new List<string>();var planes=new List<object>();
        var seen=new HashSet<ITextureData>(ReferenceEqualityComparer.Instance);
        string status="unsupported";string? error=null;string? decoder=null;
        var bytes=File.ReadAllBytes(input);
        void Emit(ITextureData? texture,string location,string category,bool tileable=false) {
            if(texture==null || !seen.Add(texture))return;
            try {
                int w=texture.Width,h=texture.Height;
                if(w<1 || h<1 || w>4096 || h>4096)throw new InvalidDataException("Unsupported image dimensions");
                var argb=texture.BitmapDataARGB1555;
                if(argb==null || argb.Length!=checked(w*h*2))throw new InvalidDataException("Invalid decoded image length");
                var rgba=new byte[w*h*4];bool opaque=true;
                for(int i=0;i<w*h;i++) {
                    int p=argb[i*2]|argb[i*2+1]<<8;
                    rgba[i*4]=(byte)(((p>>10)&31)<<3);rgba[i*4+1]=(byte)(((p>>5)&31)<<3);
                    rgba[i*4+2]=(byte)((p&31)<<3);rgba[i*4+3]=(byte)((p&0x8000)!=0?255:0);
                    opaque &= rgba[i*4+3]==255;
                }
                var pixelHash=Hash(rgba);
                var header=Encoding.ASCII.GetBytes($"{w}x{h}:");
                var id=Hash(header.Concat(rgba).ToArray());var directory=Path.Combine(store,id);
                Directory.CreateDirectory(directory);
                var raw=Path.Combine(directory,"original.rgba");
                if(!File.Exists(raw)) {File.WriteAllBytes(raw+".tmp",rgba);File.Move(raw+".tmp",raw,true);}
                else if(Hash(File.ReadAllBytes(raw))!=pixelHash)throw new InvalidDataException("Cached image checksum mismatch");
                var asset=new { id,width=w,height=h,original_sha256=pixelHash,opaque,category,
                    pixel_format=texture.PixelFormat.ToString(),original=raw,tileable };
                File.WriteAllText(Path.Combine(directory,"asset.json"),JsonSerializer.Serialize(asset,Json));
                images.Add(new { id,width=w,height=h,original_sha256=pixelHash,opaque,category,location,
                    pixel_format=texture.PixelFormat.ToString(),tileable });
            } catch(Exception ex) {warnings.Add(location+": "+ex.Message);}
        }
        void Sprites(CHR_File chr,string prefix) {
            foreach(var sprite in chr.SpriteTable)
                if(sprite.FrameTable!=null)foreach(var frame in sprite.FrameTable)
                    Emit(frame.Texture,$"{prefix}/sprite-{sprite.ID}/frame-{frame.ID}","sprites");
        }
        void Plane(SF3.MPD.Interfaces.IMPD_TiledPlane? plane,string name) {
            if(plane==null)return;
            Emit(plane.Tileset,name+"/tileset","backgrounds");
            var a=plane.TileAssignment;if(a==null)return;
            var assignment=new byte[a.Width*a.Height*2];
            for(int y=0;y<a.Height;y++)for(int x=0;x<a.Width;x++) {
                var cell=a[(byte)x,(byte)y];int at=(y*a.Width+x)*2;
                assignment[at]=cell.X;assignment[at+1]=cell.Y;
            }
            var map=Path.Combine(Path.GetDirectoryName(receipt)!,Path.GetFileName(receipt)+"-"+name+".tiles");
            File.WriteAllBytes(map,assignment);
            planes.Add(new {name,width=a.Width,height=a.Height,assignment=map,sha256=Hash(assignment),
                tileset_location=name+"/tileset"});
        }
        try {
            var scenario=(ScenarioType)int.Parse(args[0]);
            var type=FileUtils.DetermineFileType(Path.GetFileName(input));
            if(type.HasValue) {
                decoder=type.Value.ToString();
                var contexts=new Dictionary<ScenarioType,INameGetterContext>{{scenario,new NameGetterContext(scenario)}};
                using var file=FileUtils.CreateFile(new ByteData(new ByteArray(bytes)),type.Value,contexts,scenario);
                if(file is MPD_File mpd) {
                    var surfaceIds=mpd.SurfaceModelChunk?.TileTextureRowTable?.SelectMany(x=>x.GetRowCopy()).Select(x=>x&255).ToHashSet()??[];
                    foreach(var chunk in mpd.TextureChunks??[])if(chunk?.TextureTable!=null)
                        foreach(var texture in chunk.TextureTable)
                            Emit(texture,$"chunk-{chunk.ChunkIndex}/{chunk.Collection}/texture-{texture.ID}","world",
                                chunk.Collection==MPD_CollectionType.Primary && surfaceIds.Contains(texture.ID));
                    if(mpd.Animations!=null)foreach(var animation in mpd.Animations)
                        foreach(var frame in animation.AnimationFrameTable)
                            Emit(frame,$"animation-{animation.ID}/texture-{frame.ID}/frame-{frame.Frame}","world",surfaceIds.Contains(frame.ID));
                    var p=mpd.Planes;
                    if(p!=null) {
                        bool ground=(mpd.GroundImageChunkDatas?.Length>0 || mpd.GroundTilesetChunkDatas?.Length>0 || mpd.BackgroundChunkDatas?.Length>0);
                        bool sky=(mpd.SkyChunkDatas?.Length>0 || mpd.ForegroundTileChunkDatas?.Length>0);
                        if(ground && p.GroundPalette==null)warnings.Add("Ground/background palette unavailable; indexed artwork was not exported");
                        if(sky && p.SkyPalette==null)warnings.Add("Sky/foreground palette unavailable; indexed artwork was not exported");
                        if(ground && p.GroundImage==null && p.BackgroundImage==null && p.GroundTiledImage?.Tileset==null)
                            warnings.Add("Ground/background payload present but no image could be decoded");
                        if(sky && p.SkyImage==null && p.ForegroundTiledImage?.Tileset==null)
                            warnings.Add("Sky/foreground payload present but no image could be decoded");
                        if(p.GroundPalette!=null) {
                            Emit(p.GroundImage,"ground","backgrounds");Emit(p.BackgroundImage,"background","backgrounds");
                            Plane(p.GroundTiledImage,"ground");
                        }
                        if(p.SkyPalette!=null) {Emit(p.SkyImage,"sky","backgrounds");Plane(p.ForegroundTiledImage,"foreground");}
                    }
                } else if(file is CHR_File chr)Sprites(chr,"chr");
                else if(file is CHP_File chp)foreach(var entry in chp.CHR_EntriesByOffset)
                    Sprites((CHR_File)entry.Value,"chp-"+entry.Key);
                else if(file is ITableContainer tables) {
                    foreach(var table in tables.Tables)foreach(var row in table.RowObjs??[]) {
                        if(row is ITextureData direct)Emit(direct,table.Name+"/"+row.ID,"embedded");
                        foreach(var property in row.GetType().GetProperties())
                            if(typeof(ITextureData).IsAssignableFrom(property.PropertyType) && property.GetIndexParameters().Length==0)
                                try {Emit(property.GetValue(row) as ITextureData,table.Name+"/"+row.ID+"/"+property.Name,"embedded");}
                                catch(Exception ex) {warnings.Add(table.Name+"/"+property.Name+": "+ex.Message);}
                    }
                }
                if(images.Count==0 && (file is MPD_File || file is CHR_File || file is CHP_File))
                    warnings.Add("Recognized graphics file produced no images; extraction remains incomplete");
                status=warnings.Count>0?"partial":images.Count>0?"extracted":"no_images";
            }
        } catch(Exception ex) {status="failed";error=ex.ToString();}
        var result=new { schema="SF3-OFFLINE-EXTRACT-1",source=input,source_sha256=Hash(bytes),
            scenario=int.Parse(args[0]),decoder,status,error,warnings,images,planes };
        Directory.CreateDirectory(Path.GetDirectoryName(receipt)!);
        File.WriteAllText(receipt+".tmp",JsonSerializer.Serialize(result,Json));File.Move(receipt+".tmp",receipt,true);
        Console.WriteLine($"{Path.GetFileName(input)}: {status}, {images.Count} images, {warnings.Count} warnings");
        return status=="failed"?1:0;
    }
}
