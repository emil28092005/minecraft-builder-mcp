package io.github.minecraftbuilder.terrainworld;

import io.github.minecraftbuilder.terrainworld.noise.FastNoiseLite;

/** Frozen Shacraft natural-v1 profile, promoted from the approved offline study.
 * Noise objects are private and never mutated after construction; sampling is thread safe.
 */
public final class NaturalTerrain {
    private static FastNoiseLite noise(int seed, float scale, int octaves, boolean ridged) {
        var n = new FastNoiseLite(seed);
        n.SetNoiseType(FastNoiseLite.NoiseType.OpenSimplex2S);
        n.SetFrequency(1f / scale);
        n.SetFractalType(ridged ? FastNoiseLite.FractalType.Ridged : FastNoiseLite.FractalType.FBm);
        n.SetFractalOctaves(octaves); n.SetFractalGain(.48f); n.SetFractalLacunarity(2.07f);
        n.SetFractalWeightedStrength(ridged ? .7f : .25f);
        return n;
    }
    private final FastNoiseLite broad, ridges, warpX, warpZ, detail, bank;
    public NaturalTerrain(int seed) {
        broad=noise(seed,220,4,false); ridges=noise(seed+12,85,5,true);
        warpX=noise(seed+8995,165,3,false); warpZ=noise(seed+108995,165,3,false);
        detail=noise(seed+208995,17,3,false); bank=noise(seed+308995,52,3,false);
    }
    public double slope(int x,int z) {
        return Math.hypot((height(x+2,z)-height(x-2,z))/4.0,(height(x,z+2)-height(x,z-2))/4.0);
    }
    public float rockVariation(int x,int z) { return bank.GetNoise(x*2f,z*2f); }
    private static final double[][] north={{-370,-225},{-280,-295},{-180,-320},{-70,-270},{55,-295},{170,-330},{275,-270},{370,-235}};
    private static final double[][] west={{-355,-235},{-315,-135},{-360,-30},{-315,95},{-325,245},{-285,370}};
    private static final double[][] east={{345,-235},{320,-100},{355,45},{315,160},{340,300},{285,390}};
    private static final double[][] riverEast={{160,-384},{145,-280},{112,-190},{127,-100},{107,-25},{100,70},{85,145},{110,215},{55,280},{30,384}};
    private static final double[][] riverWest={{-220,65},{-190,125},{-140,175},{-110,235},{-50,285},{-20,345},{30,384}};
    private static double distance(double x,double z,double[][] path) {
        double best=Double.POSITIVE_INFINITY;
        for(int i=1;i<path.length;i++) {
            double ax=path[i-1][0],az=path[i-1][1],dx=path[i][0]-ax,dz=path[i][1]-az;
            double t=Math.max(0,Math.min(1,((x-ax)*dx+(z-az)*dz)/(dx*dx+dz*dz)));
            best=Math.min(best,Math.hypot(x-ax-t*dx,z-az-t*dz));
        }
        return best;
    }
    private static double bell(double value) { return Math.exp(-value*value); }
    private static double mix(double a,double b,double t) { return a+(b-a)*t; }
    private static double smooth(double x) { x=Math.max(0,Math.min(1,x));return x*x*(3-2*x); }
    public float height(int x,int z) {
        double wx=x+27*warpX.GetNoise(x,z),wz=z+27*warpZ.GetNoise(x,z);
        double h=62+11*broad.GetNoise((float)wx,(float)wz);
        double mountain=Math.max(145*bell(distance(wx,wz,north)/88),
            Math.max(82*bell(distance(wx,wz,west)/65),94*bell(distance(wx,wz,east)/70)));
        double ridge=Math.pow((ridges.GetNoise((float)wx,(float)wz)+1)*.5,1.55);
        h+=mountain*(.30+.70*ridge);
        h+=30*Math.exp(-Math.pow(wx/140,2)-Math.pow(wz/155,2));
        h+=11*Math.exp(-Math.pow(wx/100,2)-Math.pow((wz+115)/100,2));
        h+=14*Math.exp(-Math.pow((wx-205)/100,2)-Math.pow((wz-80)/150,2));
        h+=detail.GetNoise((float)wx,(float)wz)*(1.2+3.2*Math.min(1,mountain/90));
        double lake=Math.hypot((wx+220)/70,(wz+15)/98);
        h=mix(h,34+3*bank.GetNoise(x,z),1-smooth((lake-.55)/.85));
        double width=15+3*bank.GetNoise(x+421,z-312);
        double d=Math.min(distance(wx,wz,riverEast),distance(wx,wz,riverWest));
        h=mix(h,33+3*bank.GetNoise(x,z),bell(d/width));
        return (float)h;
    }
}
