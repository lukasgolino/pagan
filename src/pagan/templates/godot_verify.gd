# Written by `pagan build --verify-godot`: loads every resource PAGAN generated and checks it.
extends SceneTree

func _init() -> void:
	var args := OS.get_cmdline_user_args()
	var manifest_path: String = args[0] if args.size() > 0 else "res://assets/generated/manifest.json"
	var text := FileAccess.get_file_as_string(manifest_path)
	var manifest = JSON.parse_string(text)
	if typeof(manifest) != TYPE_DICTIONARY:
		printerr("PAGAN_VERIFY_FAIL cannot read manifest ", manifest_path)
		quit(1)
		return
	var failures := 0
	var checked := 0
	for name in manifest["assets"]:
		var entry: Dictionary = manifest["assets"][name]
		var sheets: Array = [entry["sheet"]]
		for v in entry.get("variants", {}):
			sheets.append(entry["variants"][v]["sheet"])
		for sheet in sheets:
			var tex = load(sheet)
			if tex == null or not (tex is Texture2D):
				printerr("PAGAN_VERIFY_FAIL texture ", sheet)
				failures += 1
		var frames_paths: Array = []
		if entry.has("godot_sprite_frames"):
			frames_paths.append(entry["godot_sprite_frames"])
		for v in entry.get("variants", {}):
			if entry["variants"][v].has("godot_sprite_frames"):
				frames_paths.append(entry["variants"][v]["godot_sprite_frames"])
		for path in frames_paths:
			var sf = load(path)
			if sf == null or not (sf is SpriteFrames):
				printerr("PAGAN_VERIFY_FAIL sprite frames ", path)
				failures += 1
				continue
			for anim in entry["animations"]:
				if not sf.has_animation(anim):
					printerr("PAGAN_VERIFY_FAIL ", path, " missing animation ", anim)
					failures += 1
					continue
				var expected: int = entry["animations"][anim]["frames"].size()
				if sf.get_frame_count(anim) != expected:
					printerr("PAGAN_VERIFY_FAIL ", path, " ", anim, " has ", sf.get_frame_count(anim), " frames, expected ", expected)
					failures += 1
				for i in sf.get_frame_count(anim):
					var t = sf.get_frame_texture(anim, i)
					if t == null or t.get_width() != entry["size"][0] or t.get_height() != entry["size"][1]:
						printerr("PAGAN_VERIFY_FAIL ", path, " ", anim, " frame ", i, " has the wrong size")
						failures += 1
			checked += 1
	if failures > 0:
		printerr("PAGAN_VERIFY_FAIL ", failures, " problems")
		quit(1)
	else:
		print("PAGAN_VERIFY_OK ", checked, " SpriteFrames checked")
		quit(0)
