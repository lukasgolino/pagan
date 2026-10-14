# Headless smoke test: instance the art test scene, let it run, and check every asset appeared and plays.
# Run: godot --headless --path examples/godot -s res://tests/check_scene.gd
extends SceneTree

var _scene: Node
var _frames := 0


func _init() -> void:
	_scene = load("res://scenes/art_test.tscn").instantiate()
	root.add_child(_scene)


func _process(_delta: float) -> bool:
	_frames += 1
	if _frames < 90:  # long enough for models to change heading
		return false
	var manifest = JSON.parse_string(FileAccess.get_file_as_string("res://assets/generated/manifest.json"))
	var expected: int = manifest["assets"].size()
	var shown := 0
	var problems := 0
	for child in _scene.get_children():
		if child is AnimatedSprite2D:
			shown += 1
			if not child.is_playing() or child.sprite_frames == null:
				printerr("CHECK_FAIL sprite not playing at ", child.position)
				problems += 1
		elif child is Sprite2D:
			shown += 1
			if child.texture == null:
				printerr("CHECK_FAIL tileset without texture")
				problems += 1
	if shown != expected:
		printerr("CHECK_FAIL showed ", shown, " assets, manifest has ", expected)
		problems += 1
	if problems == 0:
		print("CHECK_OK ", shown, " assets shown")
	quit(1 if problems else 0)
	return true
