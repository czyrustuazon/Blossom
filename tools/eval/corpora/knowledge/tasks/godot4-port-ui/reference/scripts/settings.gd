extends Node
# Autoload "Settings": user settings saved as JSON.

const PATH = "user://settings.json"

var volume := 0.8
var fullscreen := false


func _ready() -> void:
	load_settings()


func load_settings() -> void:
	if not FileAccess.file_exists(PATH):
		return
	var f := FileAccess.open(PATH, FileAccess.READ)
	if f == null:
		return
	var data = JSON.parse_string(f.get_as_text())
	if typeof(data) == TYPE_DICTIONARY:
		volume = snappedf(float(data.get("volume", volume)), 0.05)
		fullscreen = bool(data.get("fullscreen", fullscreen))
	apply()


func save_settings() -> void:
	var f := FileAccess.open(PATH, FileAccess.WRITE)
	if f == null:
		return
	f.store_string(JSON.stringify({"volume": volume, "fullscreen": fullscreen}))


func apply() -> void:
	DisplayServer.window_set_mode(
		DisplayServer.WINDOW_MODE_FULLSCREEN if fullscreen else DisplayServer.WINDOW_MODE_WINDOWED)
	AudioServer.set_bus_volume_db(0, linear_to_db(volume))
