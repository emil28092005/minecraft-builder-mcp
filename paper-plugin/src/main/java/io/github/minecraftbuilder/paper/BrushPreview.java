package io.github.minecraftbuilder.paper;

import io.github.minecraftbuilder.core.TerrainBrush;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.io.*;
import java.util.*;
import javax.imageio.ImageIO;

/** Exact sampled columns, with a shared elevation scale for before/after panels. */
public final class BrushPreview {
    private BrushPreview() { }
    public static Map<String,Object> render(TerrainBrush.Result brush) throws IOException {
        int rows=brush.before().length,cols=brush.before()[0].length;
        int low=Integer.MAX_VALUE,high=Integer.MIN_VALUE;
        for(int z=0;z<rows;z++)for(int x=0;x<cols;x++){
            low=Math.min(low,Math.min(brush.before()[z][x],brush.after()[z][x]));
            high=Math.max(high,Math.max(brush.before()[z][x],brush.after()[z][x]));
        }
        BufferedImage image=new BufferedImage(780,300,BufferedImage.TYPE_INT_RGB);Graphics2D g=image.createGraphics();
        try {
            g.setColor(new Color(0x172126));g.fillRect(0,0,780,300);g.setColor(new Color(0xECF0E9));g.setFont(new Font(Font.SANS_SERIF,Font.BOLD,16));
            String[] labels={"BEFORE","AFTER","HEIGHT CHANGE"};
            for(int panel=0;panel<3;panel++){
                int left=panel*260+10;g.drawString(labels[panel],left,24);
                double cell=Math.min(240.0/cols,240.0/rows);
                for(int z=0;z<rows;z++)for(int x=0;x<cols;x++){
                    int old=brush.before()[z][x],next=brush.after()[z][x],rgb;
                    if(panel==2){int delta=next-old;rgb=delta==0?0x34464A:delta>0?0x89CC70:0xE5A35B;}
                    else{double t=((panel==0?old:next)-low)/(double)Math.max(1,high-low);rgb=((int)(45+160*t)<<16)|((int)(83+120*t)<<8)|(int)(65+107*t);}
                    g.setColor(new Color(rgb));int x0=left+(int)(x*cell),z0=36+(int)(z*cell);
                    g.fillRect(x0,z0,(int)((x+1)*cell)-(int)(x*cell),(int)((z+1)*cell)-(int)(z*cell));
                }
                g.setColor(new Color(0xECF0E9));
            }
            g.setFont(new Font(Font.SANS_SERIF,Font.PLAIN,12));g.drawString("N (-Z) up  |  Y "+low+" .. "+high+"  |  Green: raised   Orange: lowered   Grey: unchanged",10,289);
        }finally{g.dispose();}
        ByteArrayOutputStream out=new ByteArrayOutputStream();ImageIO.write(image,"png",out);
        return Map.ofEntries(Map.entry("status","completed"),Map.entry("kind","terrain_brush_preview"),Map.entry("source","live_snapshot"),
            Map.entry("world_edited",false),Map.entry("scan_bounds",brush.bounds()),Map.entry("changed_columns",brush.changedColumns()),
            Map.entry("raised_volume",brush.raisedBlocks()),Map.entry("lowered_volume",brush.loweredBlocks()),Map.entry("dependency_blocks",brush.dependencies().size()),
            Map.entry("height_min",low),Map.entry("height_max",high),Map.entry("mimeType","image/png"),Map.entry("imageBase64",Base64.getEncoder().encodeToString(out.toByteArray())));
    }
}
