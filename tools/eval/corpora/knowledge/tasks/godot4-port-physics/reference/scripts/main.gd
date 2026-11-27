extends Node2D

@export var enemy_scene: PackedScene

var score := 0
var start_ms := 0


func _ready() -> void:
	start_ms = Time.get_ticks_msec()
	$Player.hit.connect(_on_player_hit)
	$SpawnTimer.timeout.connect(_on_spawn_timer_timeout)


func _on_spawn_timer_timeout() -> void:
	var enemy := enemy_scene.instantiate()
	enemy.position = $SpawnPoint.position + Vector2(0, randf_range(-40, 40))
	add_child(enemy)
	score += 1


func _on_player_hit() -> void:
	$Player.die()
	var survived := (Time.get_ticks_msec() - start_ms) / 1000.0
	print("Survived %.1f s, score %d" % [survived, score])
	await get_tree().create_timer(1.0).timeout
	get_tree().reload_current_scene()
