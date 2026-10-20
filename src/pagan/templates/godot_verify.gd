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
	var fonts_checked := 0
	var meshes_checked := 0
	for name in manifest["assets"]:
		var entry: Dictionary = manifest["assets"][name]
		var variants: Dictionary = entry.get("variants", {})
		var sheets: Array = [] if entry.get("mesh_only", false) else [entry.get("sheet")]  # mesh-only models have no sheet
		for v in variants:
			if variants[v].has("sheet"):
				sheets.append(variants[v]["sheet"])
			elif v == entry.get("base_variant"):
				pass  # the base colours under their own name: the base sheet, an empty swap
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
		var font_paths: Array = []
		if entry.has("font_file"):
			font_paths.append(entry["font_file"])
		for v in variants:
			if variants[v].has("font_file"):
				font_paths.append(variants[v]["font_file"])
		for path in font_paths:
			var font = load(path)
			if font == null or not (font is FontFile):
				printerr("PAGAN_VERIFY_FAIL font ", path)
				failures += 1
				continue
			var glyphs: Dictionary = entry.get("font", {}).get("glyphs", {})
			for ch in glyphs:
				if not font.has_char(ch.unicode_at(0)):
					printerr("PAGAN_VERIFY_FAIL ", path, " has no glyph for ", ch)
					failures += 1
					break
			fonts_checked += 1
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
		if entry.has("mesh"):
			failures += _check_mesh(name, entry["mesh"])
			meshes_checked += 1
		var textures: Dictionary = entry.get("textures", {})
		for texture_name in textures:
			var texture_entries: Array = [textures[texture_name]]
			texture_entries.append_array(textures[texture_name].get("variants", {}).values())
			for item in texture_entries:
				var image = load(item["png"])
				if image == null or not (image is Texture2D):
					printerr("PAGAN_VERIFY_FAIL texture ", item["png"])
					failures += 1
				if item.has("godot_material"):
					var material = load(item["godot_material"])
					if material == null or not (material is StandardMaterial3D) or material.albedo_texture == null:
						printerr("PAGAN_VERIFY_FAIL texture material ", item["godot_material"])
						failures += 1
	finished = true
	if failures > 0:
		printerr("PAGAN_VERIFY_FAIL ", failures, " problems")
		return 1
	print("PAGAN_VERIFY_OK ", sprite_frames_checked, " SpriteFrames, ", tilesets_checked, " TileSets, ", fonts_checked, " fonts, ", meshes_checked, " meshes checked")
	return 0

# A model's .glb (and .tscn): every part node where the manifest says, with its metadata and visibility,
# every animation with its loop flag, and PAGAN's materials on every surface of the .tscn.
func _check_mesh(name: String, mesh: Dictionary) -> int:
	var failures := 0
	var materials: Array = mesh.get("godot_materials", []).duplicate()
	var variants: Dictionary = mesh.get("variants", {})
	for v in variants:
		materials.append_array(variants[v].get("godot_materials", []))
	for path in materials:
		var material = load(path)
		if material == null or not (material is Material):
			printerr("PAGAN_VERIFY_FAIL ", name, " material ", path)
			failures += 1
	var scenes: Array = [mesh["glb"]]
	if mesh.has("godot_scene"):
		scenes.append(mesh["godot_scene"])
	for path in scenes:
		var packed = load(path)
		if packed == null or not (packed is PackedScene):
			printerr("PAGAN_VERIFY_FAIL ", name, " can't load ", path)
			failures += 1
			continue
		var root: Node = packed.instantiate()
		var parts: Dictionary = mesh.get("parts", {})
		for part in parts:
			var info: Dictionary = parts[part]
			var node = root.get_node_or_null(NodePath(info["node"]))
			if node == null:
				printerr("PAGAN_VERIFY_FAIL ", path, " has no node ", info["node"])
				failures += 1
				continue
			var extras: Dictionary = node.get_meta("extras", {})
			for key in info.get("meta", {}):
				if not extras.has(key) or extras[key] != info["meta"][key]:
					printerr("PAGAN_VERIFY_FAIL ", path, " node ", info["node"], " metadata ", key, " is ", extras.get(key), ", expected ", info["meta"][key])
					failures += 1
			if node is Node3D and node.visible == info.get("hidden", false):
				printerr("PAGAN_VERIFY_FAIL ", path, " node ", info["node"], " visible is ", node.visible, ", expected ", not info.get("hidden", false))
				failures += 1
			if path == mesh.get("godot_scene") and node is MeshInstance3D and node.mesh != null:
				for i in node.mesh.get_surface_count():
					if node.get_surface_override_material(i) == null:
						printerr("PAGAN_VERIFY_FAIL ", path, " node ", info["node"], " surface ", i, " has no PAGAN material")
						failures += 1
		var animations: Dictionary = mesh.get("animations", {})
		var player = root.find_child("AnimationPlayer", true, false)
		for anim in animations:
			if player == null or not player.has_animation(anim):
				printerr("PAGAN_VERIFY_FAIL ", path, " missing animation ", anim)
				failures += 1
				continue
			var looping: bool = player.get_animation(anim).loop_mode != Animation.LOOP_NONE
			if looping != animations[anim]["loop"]:
				printerr("PAGAN_VERIFY_FAIL ", path, " animation ", anim, " loop is ", looping)
				failures += 1
		root.free()
	return failures
