package io.github.minecraftbuilder.terrainworld;

import net.kyori.adventure.text.Component;
import net.kyori.adventure.text.format.NamedTextColor;
import org.bukkit.*;
import org.bukkit.block.Block;
import org.bukkit.command.*;
import org.bukkit.entity.Player;
import org.bukkit.event.*;
import org.bukkit.event.block.Action;
import org.bukkit.event.player.PlayerInteractEvent;
import org.bukkit.inventory.EquipmentSlot;
import org.bukkit.plugin.java.JavaPlugin;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

/** Explicitly enabled, two-stop personal lift for the completed station layout. */
final class StationLift implements Listener, CommandExecutor {
    private final JavaPlugin plugin;
    private final World world;
    private final Set<UUID> pending = ConcurrentHashMap.newKeySet();
    private static final Set<Material> LANDING_FLOORS = EnumSet.of(Material.SMOOTH_SANDSTONE,
        Material.SMOOTH_QUARTZ, Material.QUARTZ_BLOCK, Material.CUT_SANDSTONE,
        Material.STONE_BRICKS, Material.SMOOTH_STONE, Material.POLISHED_ANDESITE,
        Material.GOLD_BLOCK, Material.WAXED_OXIDIZED_CUT_COPPER, Material.GREEN_CONCRETE,
        Material.SPRUCE_PLANKS, Material.POLISHED_DEEPSLATE, Material.WHITE_CONCRETE);

    StationLift(JavaPlugin plugin, World world) { this.plugin = plugin; this.world = world; }

    static int selectorFloor(int x, int y, int z) {
        if (x != -6 || z != -123) return 0;
        return y == 101 ? 1 : y == 115 ? 2 : 0;
    }

    static int feetY(int floor) {
        if (floor != 1 && floor != 2) throw new IllegalArgumentException("Only completed floors 1 and 2 are available");
        return floor == 1 ? 99 : 113;
    }

    static boolean supportsLanding(Material material) { return LANDING_FLOORS.contains(material); }

    static boolean inCabin(double x, double y, double z, int floor) {
        return x >= -8 && x < -3 && z >= -122 && z < -117 && y >= feetY(floor) && y < feetY(floor) + 2;
    }

    @EventHandler(ignoreCancelled = true)
    public void onInteract(PlayerInteractEvent event) {
        if (event.getHand() != EquipmentSlot.HAND || event.getAction() != Action.RIGHT_CLICK_BLOCK) return;
        Player player = event.getPlayer();
        Block block = event.getClickedBlock();
        if (player.getWorld() != world || block == null || block.getType() != Material.GOLD_BLOCK) return;
        int floor = selectorFloor(block.getX(), block.getY(), block.getZ());
        if (floor == 0) return;
        event.setCancelled(true);
        Location at = player.getLocation();
        if (!inCabin(at.getX(), at.getY(), at.getZ(), floor)) {
            player.sendMessage(Component.text("Войди в кабину лифта.", NamedTextColor.GOLD)); return;
        }
        travel(player, floor == 1 ? 2 : 1, false);
    }

    private void travel(Player player, int floor, boolean entrance) {
        if (!pending.add(player.getUniqueId())) return;
        Location target = new Location(world, -5.5, feetY(floor), entrance ? -92.5 : -119.5, entrance ? 180 : 0, 0);
        world.getChunkAtAsync(target).whenComplete((chunk, error) -> {
            if (!plugin.isEnabled()) { pending.remove(player.getUniqueId()); return; }
            Bukkit.getScheduler().runTask(plugin, () -> {
                if (error != null || !player.isOnline() || player.getWorld() != world || !safeLanding(target)) {
                    pending.remove(player.getUniqueId());
                    if (player.isOnline()) player.sendMessage(Component.text("Лифт временно недоступен: проверь площадку назначения.", NamedTextColor.RED));
                    return;
                }
                // Loaded, checked destination. No shared cabin moves other passengers.
                boolean moved = player.teleport(target);
                pending.remove(player.getUniqueId());
                if (moved) {
                    player.playSound(target, Sound.BLOCK_NOTE_BLOCK_CHIME, .6f, floor == 2 ? 1.2f : .8f);
                    player.sendActionBar(Component.text(floor == 1 ? "1 · ВЕСТИБЮЛЬ" : "2 · SMASH", NamedTextColor.GOLD));
                }
            });
        });
    }

    private boolean safeLanding(Location target) {
        int x=target.getBlockX(),y=target.getBlockY(),z=target.getBlockZ();
        return supportsLanding(world.getBlockAt(x,y-1,z).getType())
            && world.getBlockAt(x,y,z).getType().isAir() && world.getBlockAt(x,y+1,z).getType().isAir();
    }

    @Override public boolean onCommand(CommandSender sender, Command command, String label, String[] args) {
        Player player;
        String selected;
        boolean entrance;
        if (sender instanceof Player p) {
            if (args.length > 1) return usage(sender);
            player=p; selected=args.length==0 ? "1" : args[0]; entrance=args.length==0;
        } else if (sender instanceof ConsoleCommandSender && args.length>=1 && args.length<=2) {
            player=Bukkit.getPlayerExact(args[0]); selected=args.length==2 ? args[1] : "1"; entrance=args.length==1;
        } else return usage(sender);
        if (!selected.equals("1") && !selected.equals("2")) return usage(sender);
        if (player==null || player.getWorld()!=world) {
            sender.sendMessage("Station is available in the configured lobby world."); return true;
        }
        travel(player,Integer.parseInt(selected),entrance); return true;
    }

    private boolean usage(CommandSender sender) { sender.sendMessage("/station [1|2] — vestibule or SMASH"); return true; }
}
