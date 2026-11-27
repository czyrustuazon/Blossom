@tool
extends Control

signal start_pressed
signal difficulty_chosen(index: int)

@export_range(0, 10) var lives := 3:
	set = set_lives
var score := 0:
	set = set_score
var history := PackedStringArray()

@onready var score_label: Label = $ScoreLabel
@onready var lives_label: Label = $LivesLabel
@onready var message: Label = $Message


func _ready() -> void:
	if Engine.is_editor_hint():
		return
	$StartButton.pressed.connect(_on_start_pressed)
	for i in $Difficulty.get_child_count():
		$Difficulty.get_child(i).pressed.connect(_on_difficulty_pressed.bind(i))
	message.hide()


func set_score(value: int) -> void:
	score = value
	if score_label:
		score_label.text = str(score)
		var tween := create_tween()
		tween.tween_property(score_label, "scale", Vector2.ONE, 0.25).from(Vector2(1.4, 1.4)) \
				.set_trans(Tween.TRANS_BACK).set_ease(Tween.EASE_OUT)


func set_lives(value: int) -> void:
	lives = clampi(value, 0, 10)
	if lives_label:
		lives_label.text = "Lives: %d" % lives


func show_message(text: String, seconds := 2.0) -> void:
	message.text = text
	message.show()
	await get_tree().create_timer(seconds).timeout
	message.hide()


func _on_start_pressed() -> void:
	$StartButton.hide()
	start_pressed.emit()


func _on_difficulty_pressed(index: int) -> void:
	var label: String = ["Easy", "Normal", "Hard"][index]
	history.append(label)
	if history.is_empty():
		return
	show_message("Difficulty: %s" % label)
	difficulty_chosen.emit(index)
