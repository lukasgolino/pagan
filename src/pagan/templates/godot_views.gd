# Run by `pagan preview --engine` (from a temp folder): renders one PAGAN mesh scene through Godot's real renderer
# (the ramp shader, shadows) from several sides, into PNGs. Needs a display (not --headless).
# Args: scene res path, output folder, view size, radius (metres), centre y (metres), then yaw:elevation pairs.
extends SceneTree

var _viewport: SubViewport
var _camera: Camera3D
var _views: Array = []
var _index := 0
var _wait := 0
var _out := ""
var _centre := Vector3.ZERO
var _distance := 1.0


func _init() -> void:
	var args := OS.get_cmdline_user_args()
	_out = args[1]
	var size := int(args[2])
	var radius := float(args[3])
	_centre = Vector3(0, float(args[4]), 0)
	_distance = radius * 4.0
	for pair in args.slice(5):
		var parts: PackedStringArray = pair.split(":")
		_views.append(Vector2(float(parts[0]), float(parts[1])))
	_viewport = SubViewport.new()
	_viewport.size = Vector2i(size, size)
	_viewport.transparent_bg = true
	_viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	root.add_child(_viewport)
	var model: Node3D = load(args[0]).instantiate()
	_viewport.add_child(model)
	var player: AnimationPlayer = model.find_child("AnimationPlayer", true, false)
	if player != null and player.has_animation("RESET"):
		player.play("RESET")
	var sun := DirectionalLight3D.new()
	sun.shadow_enabled = true
	sun.rotation_degrees = Vector3(-50, -35, 0)  # from the upper left, behind the camera's shoulder
	_viewport.add_child(sun)
	var environment := Environment.new()
	environment.background_mode = Environment.BG_CLEAR_COLOR
	environment.tonemap_mode = Environment.TONE_MAPPER_LINEAR
	var world := WorldEnvironment.new()
	world.environment = environment
	_viewport.add_child(world)
	_camera = Camera3D.new()
	_camera.projection = Camera3D.PROJECTION_ORTHOGONAL
	_camera.size = radius * 2.2
	_camera.near = 0.01
	_camera.far = _distance * 3.0
	_viewport.add_child(_camera)
	_place(0)


func _place(i: int) -> void:
	var view: Vector2 = _views[i]
	var yaw := deg_to_rad(view.x)
	var pitch := deg_to_rad(view.y)
	var eye := _centre + _distance * Vector3(cos(pitch) * sin(yaw), sin(pitch), cos(pitch) * cos(yaw))
	var up := Vector3.UP if absf(view.y) < 89.0 else Vector3.FORWARD
	_camera.transform = Transform3D(Basis(), eye).looking_at(_centre, up)


func _process(_delta: float) -> bool:
	_wait += 1
	if _wait < 4:  # let shadows and the viewport settle
		return false
	_viewport.get_texture().get_image().save_png("%s/view_%02d.png" % [_out, _index])
	_index += 1
	_wait = 0
	if _index >= _views.size():
		print("PAGAN_VIEWS_OK ", _index)
		quit(0)
		return true
	_place(_index)
	return false
