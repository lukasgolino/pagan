# Lint

Lint rules: what each means and how to fix it.

## Lint rules

Errors: E000 command/usage, E001 YAML/field, E002 unknown pixel key, E003 grid size, E004 missing
animation frame, E005 palette problem, E006 variant problem, E007 outline or shadow clipped at the edge, E008 pivot,
E009 inline palette in strict mode, E010 derived frame, E011 outline required, E012 duplicate asset name,
E013 model problem, E014 rig / mesh problem (unknown rig id or parent, parent cycle, a hidden carving part when
meshes are exported), E015 translucent colour with `require_opaque`, E016 timeline problem (`scenes/*.timeline.yaml`). E003 also: a size that isn't a multiple of `supersample`.

Warnings: W001 orphan pixel, W002 unused frame, W003 too many ramps, W004 empty frame, W005 visible area
jumps between frames, W006 made under an older style version, W007 too much change between frames,
W008 too many shades from one ramp (sprites) / in one material (models), when `max_ramp_steps` is set.
Mesh export only (`export` has "mesh"): W009 a model overrides `[mesh] voxel_size`, W010 a part's voxels are
separate pieces, W011 a rig pivot outside its part; W012 `directions: 0` (mesh only) without "mesh" in `export`.
W013 (any model): a part id has no voxels left, because later parts cover (or carve) all of it.
W014 (any asset): the built sheet is over 16384 px on a side (many engines, Godot too, won't load it): set
`sheet_columns` (sprites) or `columns` (tilesets), `trim: true` (mostly transparent sprite frames), or split the asset.
Turn warnings off project-wide with `[lint] disable`, or per asset/frame/animation with the file's `lint:`.
W001 isn't checked on 3D models (a rendered orphan can't be fixed pixel by pixel).
