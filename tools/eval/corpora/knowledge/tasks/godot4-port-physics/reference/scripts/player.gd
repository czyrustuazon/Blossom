extends CharacterBody2D

signal hit

@export var speed := 220.0
@export var jump_velocity := -400.0
@export_range(0, 2000) var gravity := 900.0

@onready var sprite: AnimatedSprite2D = $AnimatedSprite2D


func _physics_process(delta: float) -> void:
	velocity.y += gravity * delta
	var dir := Input.get_action_strength("ui_right") - Input.get_action_strength("ui_left")
	velocity.x = dir * speed
	if is_on_floor() and Input.is_action_just_pressed("ui_accept"):
		velocity.y = jump_velocity
	move_and_slide()

	if dir != 0:
		sprite.flip_h = dir < 0
		sprite.play("run")
	else:
		sprite.play("idle")

	for i in get_slide_collision_count():
		var col := get_slide_collision(i)
		if col.get_collider().is_in_group("enemies"):
			hit.emit()


func die() -> void:
	set_physics_process(false)
	sprite.play("hurt")
	await get_tree().create_timer(0.5).timeout
	queue_free()
