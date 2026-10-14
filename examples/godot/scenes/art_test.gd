# Shows every asset from PAGAN's manifest: sprites play their animations, models cycle through their
# headings (playing an animation per heading when they have one), tilesets show their atlas.
extends Node2D

const MANIFEST := "res://assets/generated/manifest.json"
const PAD := 8
const HEADING_SECONDS := 1.0

var _models: Array = []  # [AnimatedSprite2D, headings: Array, animation prefix: String]
var _heading := 0
var _clock := 0.0


func _ready() -> void:
	var manifest = JSON.parse_string(FileAccess.get_file_as_string(MANIFEST))
	if typeof(manifest) != TYPE_DICTIONARY:
		push_error("Can't read %s: run `pagan build` in examples/demo first." % MANIFEST)
		return
	var x := PAD
	var y := PAD
	var row_height := 0
	var names: Array = manifest["assets"].keys()
	names.sort()
	for asset_name in names:
		var entry: Dictionary = manifest["assets"][asset_name]
		var node := _make_node(entry)
		var size := _display_size(entry)
		if x + size.x > 480 - PAD:
			x = PAD
			y += row_height + 14
			row_height = 0
		node.position = Vector2(x, y)
		add_child(node)
		var label := Label.new()
		label.text = asset_name
		label.position = Vector2(x, y + size.y)
		label.add_theme_font_size_override("font_size", 8)
		add_child(label)
		x += size.x + PAD
		row_height = max(row_height, size.y)


func _display_size(entry: Dictionary) -> Vector2i:
	if entry["kind"] == "tileset":
		var count: int = entry["frames"].size()
		var cols: int = min(count, entry["columns"])
		return Vector2i(entry["size"][0] * cols, entry["size"][1] * int(ceil(float(count) / cols)))
	return Vector2i(entry["size"][0], entry["size"][1])


func _make_node(entry: Dictionary) -> Node2D:
	if entry["kind"] == "tileset":
		var atlas := Sprite2D.new()
		atlas.texture = load(entry["sheet"])
		atlas.centered = false
		return atlas
	var sprite := AnimatedSprite2D.new()
	sprite.sprite_frames = load(entry["godot_sprite_frames"])
	sprite.centered = false  # the grid layout places top-left corners; games use centered + godot_offset
	var animations: Array = entry["animations"].keys()
	if entry["kind"] == "model":
		var prefix := ""
		for anim in animations:
			for heading in entry["headings"]:
				if anim != heading and anim.ends_with("_" + heading):
					prefix = anim.trim_suffix("_" + heading) + "_"
		_models.append([sprite, entry["headings"], prefix])
		sprite.play(prefix + entry["headings"][0])
	else:
		var playing: String = animations[0]
		for anim in animations:
			if entry["animations"][anim]["frames"].size() > 1:
				playing = anim
				break
		sprite.play(playing)
	return sprite


func _process(delta: float) -> void:
	_clock += delta
	if _clock < HEADING_SECONDS:
		return
	_clock = 0.0
	_heading += 1
	for model in _models:
		var headings: Array = model[1]
		model[0].play(model[2] + headings[_heading % headings.size()])
