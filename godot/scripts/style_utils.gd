class_name StyleUtils
extends RefCounted

static func create_flat_style(
	bg_color: Color,
	border_color: Color = Color.TRANSPARENT,
	border_width: int = 0,
	corner_radius: int = 0
) -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = bg_color
	style.border_color = border_color
	style.border_width_bottom = border_width
	style.border_width_top = border_width
	style.border_width_left = border_width
	style.border_width_right = border_width
	style.corner_radius_top_left = corner_radius
	style.corner_radius_top_right = corner_radius
	style.corner_radius_bottom_left = corner_radius
	style.corner_radius_bottom_right = corner_radius
	return style
