extends KinematicBody2D

signal hit

export var speed = 220.0
export var jump_velocity = -400.0
export(float, 0, 2000) var gravity = 900.0

var velocity = Vector2.ZERO

onready var sprite = $AnimatedSprite


func _physics_process(delta):
	velocity.y += gravity * delta
	var dir = Input.get_action_strength("ui_right") - Input.get_action_strength("ui_left")
	velocity.x = dir * speed
	if is_on_floor() and Input.is_action_just_pressed("ui_accept"):
		velocity.y = jump_velocity
	velocity = move_and_slide(velocity, Vector2.UP)

	if dir != 0:
		sprite.flip_h = dir < 0
		sprite.play("run")
	else:
		sprite.play("idle")

	for i in get_slide_count():
		var col = get_slide_collision(i)
		if col.collider.is_in_group("enemies"):
			emit_signal("hit")


func die():
	set_physics_process(false)
	sprite.play("hurt")
	yield(get_tree().create_timer(0.5), "timeout")
	queue_free()
