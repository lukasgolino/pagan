# Headless smoke test: instance the mesh test scene, let it run, and check every mesh appeared, plays its
# animation and has PAGAN's materials. Run: godot --headless --path examples/godot -s res://tests/check_mesh_scene.gd
extends SceneTree

var _scene: Node
var _frames := 0


func _init() -> void:
	_scene = load("res://scenes/mesh_test.tscn").instantiate()
	root.add_child(_scene)


func _process(_delta: float) -> bool:
	_frames += 1
	if _frames < 60:
		return false
	var manifest = JSON.parse_string(FileAccess.get_file_as_string("res://assets/generated/manifest.json"))
	var expected := 0
	for asset_name in manifest["assets"]:
		if manifest["assets"][asset_name].has("mesh"):
			expected += 1
	var problems := 0
	for model in _scene.models:
		var player: AnimationPlayer = model.find_child("AnimationPlayer", true, false)
		var mesh: Dictionary = manifest["assets"][String(model.name)]["mesh"]
		var loops: bool = mesh["animations"].values().any(func(a): return a["loop"])
		if loops and (player == null or not player.is_playing()):
			printerr("CHECK_FAIL ", model.name, " isn't animating")
			problems += 1
		if model.rotation.y == 0.0:
			printerr("CHECK_FAIL ", model.name, " isn't turning")
			problems += 1
		var body: MeshInstance3D = model.get_node(NodePath(mesh["root"]))
		if body.get_surface_override_material(0) == null:
			printerr("CHECK_FAIL ", model.name, " has no PAGAN material")
			problems += 1
	# What README.md tells games to do: face a target, read part metadata, knock a part off.
	for model in _scene.models:
		model.look_at(model.global_position + Vector3(1, 0, 0), Vector3.UP, true)
		var mesh: Dictionary = manifest["assets"][String(model.name)]["mesh"]
		for part in mesh["parts"]:
			var info: Dictionary = mesh["parts"][part]
			var node: Node3D = model.get_node(NodePath(info["node"]))
			if info["meta"].get("detachable", false) and node.get_meta("extras").get("detachable", false):
				var before := node.global_position
				node.reparent(_scene)
				if node.global_position.distance_to(before) > 0.001 or node.get_parent() != _scene:
					printerr("CHECK_FAIL ", model.name, " part ", part, " moved when detached")
					problems += 1
				else:
					print("detached ", model.name, "/", part)
	if _scene.models.size() != expected or expected == 0:
		printerr("CHECK_FAIL showed ", _scene.models.size(), " meshes, manifest has ", expected)
		problems += 1
	if problems == 0:
		print("CHECK_OK ", expected, " meshes shown")
	quit(1 if problems else 0)
	return true
