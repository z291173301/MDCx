import re

with open('mdcx/views/MDCx.py', 'r', encoding='utf-8') as f:
    content = f.read()

w_factor = 1080 / 1089
h_factor = 720 / 700

unchanged_buttons = {
    'pushButton_select_media_folder',
    'pushButton_start_cap',
    'pushButton_start_cap2',
    'pushButton_view_failed_list',
    'pushButton_check_net',
    'pushButton_net_copy',
    'pushButton_net_retry',
    'pushButton_save_new_config',
    'pushButton_save_new_config_tool',
    'pushButton_init_config',
    'pushButton_init_config_tool',
    'pushButton_save_config',
    'pushButton_save_config_tool',
    'comboBox_change_config',
    'comboBox_change_config_tool',
}

def process_geometry(line):
    widget_match = re.search(r'self\.(\w+)', line)
    if not widget_match:
        return line
    widget_name = widget_match.group(1)
    if widget_name in unchanged_buttons:
        return line
    rect_match = re.search(r'QRect\((\d+),\s*(\d+),\s*(\d+),\s*(\d+)\)', line)
    if rect_match:
        x = int(rect_match.group(1))
        y = int(rect_match.group(2))
        w = int(rect_match.group(3))
        h = int(rect_match.group(4))
        new_x = int(round(x * w_factor))
        new_y = int(round(y * h_factor))
        new_w = int(round(w * w_factor))
        new_h = int(round(h * h_factor))
        new_line = line.replace(
            f'QRect({x}, {y}, {w}, {h})',
            f'QRect({new_x}, {new_y}, {new_w}, {new_h})'
        )
        return new_line
    return line

lines = content.split('\n')
new_lines = []
for line in lines:
    if 'MDCx.resize(1089, 700)' in line:
        line = line.replace('MDCx.resize(1089, 700)', 'MDCx.resize(1080, 720)')
    if '.setGeometry(QtCore.QRect(' in line:
        line = process_geometry(line)
    new_lines.append(line)

with open('mdcx/views/MDCx.py', 'w', encoding='utf-8') as f:
    f.write('\n'.join(new_lines))

print('Done. Lines:', len(new_lines))
