extends CharacterBody2D

@export var speed := 80.0
@export var gravity := 900.0


func _ready() -> void:
	add_to_group("enemies")
	rotation = deg_to_rad(randf_range(-10, 10))
	$VisibleOnScreenNotifier2D.screen_exited.connect(_on_screen_exited)


func _physics_process(delta: float) -> void:
	velocity.x = -speed
	velocity.y += gravity * delta
	move_and_slide()


func _on_screen_exited() -> void:
	queue_free()
