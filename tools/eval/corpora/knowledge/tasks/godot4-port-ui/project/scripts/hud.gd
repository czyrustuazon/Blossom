tool
extends Control

signal start_pressed
signal difficulty_chosen(index)

export(int, 0, 10) var lives = 3 setget set_lives
var score = 0 setget set_score
var history = PoolStringArray()

onready var score_label = $ScoreLabel
onready var lives_label = $LivesLabel
onready var message = $Message
onready var tween = $Tween


func _ready():
	if Engine.editor_hint:
		return
	$StartButton.connect("pressed", self, "_on_start_pressed")
	for i in $Difficulty.get_child_count():
		$Difficulty.get_child(i).connect("pressed", self, "_on_difficulty_pressed", [i])
	message.hide()


func set_score(value):
	score = value
	if score_label:
		score_label.text = str(score)
		tween.interpolate_property(score_label, "rect_scale", Vector2(1.4, 1.4), Vector2.ONE, 0.25,
				Tween.TRANS_BACK, Tween.EASE_OUT)
		tween.start()


func set_lives(value):
	lives = int(clamp(value, 0, 10))
	if lives_label:
		lives_label.text = "Lives: %d" % lives


func show_message(text, seconds = 2.0):
	message.text = text
	message.show()
	yield(get_tree().create_timer(seconds), "timeout")
	message.hide()


func _on_start_pressed():
	$StartButton.hide()
	emit_signal("start_pressed")


func _on_difficulty_pressed(index):
	var label = ["Easy", "Normal", "Hard"][index]
	history.append(label)
	if history.empty():
		return
	show_message("Difficulty: %s" % label)
	emit_signal("difficulty_chosen", index)
