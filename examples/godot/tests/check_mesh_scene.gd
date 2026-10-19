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
	if _scene.models.size() != expected or expected == 0:
		printerr("CHECK_FAIL showed ", _scene.models.size(), " meshes, manifest has ", expected)
		problems += 1
	if problems == 0:
		print("CHECK_OK ", expected, " meshes shown")
	quit(1 if problems else 0)
	return true
