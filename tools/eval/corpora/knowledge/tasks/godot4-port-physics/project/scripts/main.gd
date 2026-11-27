extends Node2D

export(PackedScene) var enemy_scene

var score = 0
var start_ms = 0


func _ready():
	randomize()
	start_ms = OS.get_ticks_msec()
	$Player.connect("hit", self, "_on_player_hit")
	$SpawnTimer.connect("timeout", self, "_on_spawn_timer_timeout")


func _on_spawn_timer_timeout():
	var enemy = enemy_scene.instance()
	enemy.position = $SpawnPoint.position + Vector2(0, rand_range(-40, 40))
	add_child(enemy)
	score += 1


func _on_player_hit():
	$Player.die()
	var survived = (OS.get_ticks_msec() - start_ms) / 1000.0
	print("Survived %.1f s, score %d" % [survived, score])
	yield(get_tree().create_timer(1.0), "timeout")
	get_tree().reload_current_scene()
