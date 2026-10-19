# Shows every PAGAN mesh from the manifest (`export` has "mesh"): each model turns on its own turntable and plays
# its first looping animation, under a sun that moves, so the palette-locked ramp shader and shadows can be judged.
# Rendered at the project's 480x270 and upscaled with nearest filtering, like a low-res 3D game.
extends Node3D

const MANIFEST := "res://assets/generated/manifest.json"
const TURN_SPEED := 0.6  # radians per second
const GAP := 1.0  # metres between models

var models: Array[Node3D] = []
var _sun: DirectionalLight3D
var _clock := 0.0


func _ready() -> void:
	var manifest = JSON.parse_string(FileAccess.get_file_as_string(MANIFEST))
	if typeof(manifest) != TYPE_DICTIONARY:
		push_error("Can't read %s: run `pagan build` in examples/demo first." % MANIFEST)
		return
	var names: Array = manifest["assets"].keys().filter(func(n): return manifest["assets"][n].has("mesh"))
	names.sort()
	var x := 0.0
	var tallest := 0.0
	for asset_name in names:
		var mesh: Dictionary = manifest["assets"][asset_name]["mesh"]
		var low: Array = mesh["bounds"]["min"]
		var high: Array = mesh["bounds"]["max"]
		var radius: float = max(Vector2(low[0], low[2]).length(), Vector2(high[0], high[2]).length())
		var model: Node3D = load(mesh["godot_scene"]).instantiate()
		model.name = asset_name
		x += radius
		model.position = Vector3(x, 0, 0)
		x += radius + GAP
		tallest = max(tallest, high[1])
		add_child(model)
		models.append(model)
		var player: AnimationPlayer = model.find_child("AnimationPlayer", true, false)
		for anim in mesh.get("animation_order", []):
			if mesh["animations"][anim]["loop"]:
				player.play(anim)
				break
	var width := x - GAP

	_sun = DirectionalLight3D.new()
	_sun.shadow_enabled = true
	add_child(_sun)

	var ground := MeshInstance3D.new()
	var plane := PlaneMesh.new()
	plane.size = Vector2(width + 8.0, 12.0)
	var ground_material := StandardMaterial3D.new()
	ground_material.albedo_color = Color(0.16, 0.22, 0.3)
	plane.material = ground_material
	ground.mesh = plane
	ground.position = Vector3(width / 2.0, 0, 0)
	add_child(ground)

	var environment := Environment.new()
	environment.background_mode = Environment.BG_COLOR
	environment.background_color = Color(0.10, 0.16, 0.24)
	environment.tonemap_mode = Environment.TONE_MAPPER_LINEAR  # keeps the ramp shader's palette colours exact
	var world := WorldEnvironment.new()
	world.environment = environment
	add_child(world)

	var camera := Camera3D.new()
	var target := Vector3(width / 2.0, tallest * 0.4, 0)
	camera.position = target + Vector3(0, width * 0.3 + 0.6, width * 0.55 + 1.2)
	add_child(camera)
	camera.look_at(target)


func _process(delta: float) -> void:
	_clock += delta
	for model in models:
		model.rotate_y(delta * TURN_SPEED)
	if _sun != null:
		_sun.rotation = Vector3(deg_to_rad(-40.0 - 15.0 * sin(_clock * 0.5)), _clock * 0.35, 0)
