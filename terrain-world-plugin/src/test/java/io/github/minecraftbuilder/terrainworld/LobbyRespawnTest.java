package io.github.minecraftbuilder.terrainworld;

import org.bukkit.Location;
import org.bukkit.World;
import org.bukkit.entity.Player;
import org.bukkit.event.player.PlayerRespawnEvent;
import org.junit.jupiter.api.Test;
import java.lang.reflect.Proxy;
import static org.junit.jupiter.api.Assertions.*;

class LobbyRespawnTest {
    @Test void configuredLobbyDeathUsesPlazaFeetEvenWhenVanillaSelectedBarrierRoof() {
        World lobby = world();
        Location spawn = new Location(lobby, .5, 96, 43.5, 180, 0);
        LobbyRespawn listener = new LobbyRespawn(lobby, spawn);
        spawn.setY(300); // The listener retains its own configuration snapshot.
        var event = event(lobby, new Location(lobby, .5, 131, 43.5), PlayerRespawnEvent.RespawnReason.DEATH);
        listener.onRespawn(event);
        assertDestination(event.getRespawnLocation(), lobby, .5, 96, 43.5, 180, 0);
        event.getRespawnLocation().setY(200);
        var next = event(lobby, new Location(world(), 8, 70, 9), PlayerRespawnEvent.RespawnReason.DEATH);
        listener.onRespawn(next);
        assertDestination(next.getRespawnLocation(), lobby, .5, 96, 43.5, 180, 0);
    }

    @Test void otherWorldDeathsAreUnchangedEvenWhenTheirDestinationIsLobby() {
        World lobby = world(), other = world();
        var listener = new LobbyRespawn(lobby, new Location(lobby, .5, 96, 43.5, 180, 0));
        var event = event(other, new Location(lobby, 11, 115, 23, 90, 10), PlayerRespawnEvent.RespawnReason.DEATH);
        listener.onRespawn(event);
        assertDestination(event.getRespawnLocation(), lobby, 11, 115, 23, 90, 10);
    }

    @Test void absentConfigurationAndNonDeathRespawnsKeepOriginalBehavior() {
        World lobby = world();
        var disabled = new LobbyRespawn(lobby, null);
        var death = event(lobby, new Location(lobby, 11, 115, 23), PlayerRespawnEvent.RespawnReason.DEATH);
        disabled.onRespawn(death);
        assertDestination(death.getRespawnLocation(), lobby, 11, 115, 23, 0, 0);
        var enabled = new LobbyRespawn(lobby, new Location(lobby, .5, 96, 43.5, 180, 0));
        for (var reason : PlayerRespawnEvent.RespawnReason.values()) {
            if (reason == PlayerRespawnEvent.RespawnReason.DEATH) continue;
            var event = event(lobby, new Location(lobby, 11, 115, 23), reason);
            enabled.onRespawn(event);
            assertDestination(event.getRespawnLocation(), lobby, 11, 115, 23, 0, 0);
        }
    }

    private static PlayerRespawnEvent event(World origin, Location destination, PlayerRespawnEvent.RespawnReason reason) {
        Player player = (Player) Proxy.newProxyInstance(Player.class.getClassLoader(), new Class<?>[]{Player.class},
            (proxy, method, args) -> {
                if (method.getName().equals("getWorld")) return origin;
                throw new AssertionError("Unexpected player call: " + method.getName());
            });
        return new PlayerRespawnEvent(player, destination, false, false, false, reason);
    }

    private static World world() {
        return (World) Proxy.newProxyInstance(World.class.getClassLoader(), new Class<?>[]{World.class},
            (proxy, method, args) -> { throw new AssertionError("Must not query terrain or world state: " + method.getName()); });
    }

    private static void assertDestination(Location location, World world, double x, double y, double z, float yaw, float pitch) {
        assertSame(world, location.getWorld());
        assertEquals(x, location.getX()); assertEquals(y, location.getY()); assertEquals(z, location.getZ());
        assertEquals(yaw, location.getYaw()); assertEquals(pitch, location.getPitch());
    }
}
