import { z } from 'zod';

const coordinate = z.number().int().min(-30_000_000).max(30_000_000);
const point = z.object({ x: coordinate, z: coordinate }).strict();
const position = z.object({ x: coordinate, y: z.number().int().min(-4096).max(4096), z: coordinate }).strict();
const elevation = z.number().finite().min(-4096).max(4096);
const falloff = z.number().finite().min(1).max(2048);
const material = z.enum(['minecraft:stone','minecraft:andesite','minecraft:granite','minecraft:diorite','minecraft:deepslate',
  'minecraft:cobbled_deepslate','minecraft:dirt','minecraft:grass_block','minecraft:moss_block','minecraft:sandstone','minecraft:terracotta']);
const feature = z.discriminatedUnion('type', [
  z.object({ type: z.literal('hill'), center: point, radius: z.number().min(1).max(2048), height: elevation, falloff }).strict(),
  z.object({ type: z.literal('basin'), center: point, radius: z.number().min(1).max(2048), height: elevation, falloff }).strict(),
  z.object({ type: z.literal('plateau'), min: point, max: point, height: elevation, falloff }).strict(),
  z.object({ type: z.literal('ridge'), points: z.array(point).min(2).max(32), width: z.number().min(1).max(1024), height: elevation, falloff }).strict(),
  z.object({ type: z.literal('channel'), points: z.array(point).min(2).max(32), width: z.number().min(1).max(1024), height: elevation, falloff }).strict(),
  z.object({ type: z.literal('terrace'), step: z.number().min(1).max(128), strength: z.number().min(0).max(1) }).strict(),
]);
export const terrainRecipe = z.object({
  version: z.literal(1), min: position, max: position, base_height: z.number().int().min(-4096).max(4096),
  seed: z.number().int().min(-2147483648).max(2147483647), mode: z.enum(['sculpt','fill','cut']),
  noise: z.object({ amplitude: z.number().min(0).max(256), scale: z.number().min(1).max(4096) }).strict(),
  palette: z.object({ rock: material, soil: material, surface: material, soil_depth: z.number().int().min(0).max(16) }).strict(),
  features: z.array(feature).max(64), preserve: z.array(z.object({ min: position, max: position }).strict()).max(64),
}).strict();


export const terrainBrush = z.object({
  min: position, max: position, center: point, radius: z.number().int().min(1).max(16),
  action: z.enum(['raise','lower','flatten','smooth']),
  amount: z.number().int().min(1).max(32).optional(), height: z.number().int().min(-4096).max(4096).optional(),
  strength: z.number().min(0).max(1).default(1), falloff: z.number().min(0).max(1).default(0.5),
  smooth_radius: z.number().int().min(1).max(3).optional(),
  preserve: z.array(z.object({min: position,max: position}).strict()).max(64).default([]),
}).strict();
