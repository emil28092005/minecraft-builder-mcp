package dev.minecraftbuilder.camera.mixin;

import dev.minecraftbuilder.camera.CameraClient;
import net.minecraft.client.DeltaTracker;
import net.minecraft.client.renderer.GameRenderer;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(GameRenderer.class)
abstract class GameRendererMixin {
    @Inject(method = "render", at = @At("TAIL"))
    private void mcb$afterFrame(DeltaTracker deltaTracker, boolean renderWorld, CallbackInfo callback) {
        CameraClient.afterRender(renderWorld);
    }
}
