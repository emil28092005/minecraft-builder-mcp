package io.github.minecraftbuilder.terrainworld;

import org.bukkit.Location;
import org.bukkit.World;
import org.bukkit.event.EventHandler;
import org.bukkit.event.Listener;
import org.bukkit.event.player.PlayerRespawnEvent;

/** A configured indoor spawn must survive vanilla's highest-surface respawn search. */
final class LobbyRespawn implements Listener {
    private final World world;
    private final Location configuredSpawn;

    LobbyRespawn(World world, Location configuredSpawn) {
        this.world = world;
        this.configuredSpawn = configuredSpawn == null ? null : configuredSpawn.clone();
    }

    @EventHandler
    public void onRespawn(PlayerRespawnEvent event) {
        if (configuredSpawn != null && event.getRespawnReason() == PlayerRespawnEvent.RespawnReason.DEATH
            && event.getPlayer().getWorld() == world)
            event.setRespawnLocation(configuredSpawn);
    }
}
