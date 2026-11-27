extends KinematicBody2D

export var speed = 80.0
export var gravity = 900.0

var velocity = Vector2()


func _ready():
	add_to_group("enemies")
	rotation = deg2rad(rand_range(-10, 10))
	$VisibilityNotifier2D.connect("screen_exited", self, "_on_screen_exited")


func _physics_process(delta):
	velocity.x = -speed
	velocity.y += gravity * delta
	velocity = move_and_slide(velocity, Vector2.UP)


func _on_screen_exited():
	queue_free()
