extends Node
# Autoload "Settings": user settings saved as JSON.

const PATH = "user://settings.json"

var volume = 0.8
var fullscreen = false


func _ready():
	load_settings()


func load_settings():
	var f = File.new()
	if not f.file_exists(PATH):
		return
	f.open(PATH, File.READ)
	var data = parse_json(f.get_as_text())
	f.close()
	if typeof(data) == TYPE_DICTIONARY:
		volume = stepify(float(data.get("volume", volume)), 0.05)
		fullscreen = bool(data.get("fullscreen", fullscreen))
	apply()


func save_settings():
	var f = File.new()
	f.open(PATH, File.WRITE)
	f.store_string(to_json({"volume": volume, "fullscreen": fullscreen}))
	f.close()


func apply():
	OS.window_fullscreen = fullscreen
	AudioServer.set_bus_volume_db(0, linear2db(volume))
