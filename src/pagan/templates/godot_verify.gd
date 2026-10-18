# Run by `pagan build --verify-godot` (from a temp folder): loads every resource PAGAN generated and checks it.
# Any script error ends the run with exit 1 at once: the checks run in `_check`, which sets `finished` only when it
# gets to the end (a GDScript runtime error returns from the function with a default value instead of raising).
extends SceneTree

var finished := false

func _init() -> void:
	var code := _check()
	if not finished:
		printerr("PAGAN_VERIFY_FAIL the check script hit an error (see SCRIPT ERROR above)")
		code = 1
	quit(code)

func _check() -> int:
	var args := OS.get_cmdline_user_args()
	var manifest_path: String = args[0] if args.size() > 0 else "res://assets/generated/manifest.json"
	var text := FileAccess.get_file_as_string(manifest_path)
	var manifest = JSON.parse_string(text)
	if typeof(manifest) != TYPE_DICTIONARY or typeof(manifest.get("assets")) != TYPE_DICTIONARY:
		printerr("PAGAN_VERIFY_FAIL cannot read manifest ", manifest_path)
		finished = true
		return 1
	var failures := 0
	var sprite_frames_checked := 0
	var tilesets_checked := 0
	for name in manifest["assets"]:
		var entry: Dictionary = manifest["assets"][name]
		var variants: Dictionary = entry.get("variants", {})
		var sheets: Array = [entry.get("sheet")]
		for v in variants:
			if variants[v].has("sheet"):
				sheets.append(variants[v]["sheet"])
			elif typeof(variants[v].get("swap")) != TYPE_DICTIONARY or variants[v]["swap"].is_empty():
				# variant_sheets = false: the variant is a swap table only
				printerr("PAGAN_VERIFY_FAIL ", name, " variant ", v, " has neither a sheet nor a swap table")
				failures += 1
		for sheet in sheets:
			var tex = load(sheet) if typeof(sheet) == TYPE_STRING else null
			if tex == null or not (tex is Texture2D):
				printerr("PAGAN_VERIFY_FAIL texture ", sheet)
				failures += 1
		var tileset_paths: Array = []
		if entry.has("godot_tileset"):
			tileset_paths.append(entry["godot_tileset"])
		for v in variants:
			if variants[v].has("godot_tileset"):
				tileset_paths.append(variants[v]["godot_tileset"])
		for path in tileset_paths:
			var ts = load(path)
			if ts == null or not (ts is TileSet) or ts.get_source_count() != 1:
				printerr("PAGAN_VERIFY_FAIL tileset ", path)
				failures += 1
				continue
			var source = ts.get_source(ts.get_source_id(0))
			if source.get_tiles_count() != entry.get("tiles", {}).size():
				printerr("PAGAN_VERIFY_FAIL ", path, " has ", source.get_tiles_count(), " tiles, expected ", entry.get("tiles", {}).size())
				failures += 1
			if ts.tile_size != Vector2i(entry["size"][0], entry["size"][1]):
				printerr("PAGAN_VERIFY_FAIL ", path, " tile size ", ts.tile_size)
				failures += 1
			tilesets_checked += 1
		var frames_paths: Array = []
		if entry.has("godot_sprite_frames"):
			frames_paths.append(entry["godot_sprite_frames"])
		for v in variants:
			if variants[v].has("godot_sprite_frames"):
				frames_paths.append(variants[v]["godot_sprite_frames"])
		var animations: Dictionary = entry.get("animations", {})
		for path in frames_paths:
			var sf = load(path)
			if sf == null or not (sf is SpriteFrames):
				printerr("PAGAN_VERIFY_FAIL sprite frames ", path)
				failures += 1
				continue
			for anim in animations:
				if not sf.has_animation(anim):
					printerr("PAGAN_VERIFY_FAIL ", path, " missing animation ", anim)
					failures += 1
					continue
				var expected: int = animations[anim].get("frames", []).size()
				if sf.get_frame_count(anim) != expected:
					printerr("PAGAN_VERIFY_FAIL ", path, " ", anim, " has ", sf.get_frame_count(anim), " frames, expected ", expected)
					failures += 1
				for i in sf.get_frame_count(anim):
					var t = sf.get_frame_texture(anim, i)
					if t == null or t.get_width() != entry["size"][0] or t.get_height() != entry["size"][1]:
						printerr("PAGAN_VERIFY_FAIL ", path, " ", anim, " frame ", i, " has the wrong size")
						failures += 1
			sprite_frames_checked += 1
	finished = true
	if failures > 0:
		printerr("PAGAN_VERIFY_FAIL ", failures, " problems")
		return 1
	print("PAGAN_VERIFY_OK ", sprite_frames_checked, " SpriteFrames, ", tilesets_checked, " TileSets checked")
	return 0
