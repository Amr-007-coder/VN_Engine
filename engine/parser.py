from engine.config import CHAR_PARS


def parse(text: str):
    words = []
    seperators = CHAR_PARS.values()

    temp = ""
    current_type = ""
    for char in text:
        if "value" in current_type:
            if char == CHAR_PARS.value.end:
                if temp:
                    words.append((temp, current_type))
                    temp = ""
                current_type = current_type.replace("value", "")
            else:
                temp += char
            continue
        if char in seperators:
            if temp:
                words.append((temp, current_type))
                temp = ""
            if char == CHAR_PARS.value.start:
                current_type += "value"
            elif char == CHAR_PARS.value.end:
                current_type = current_type.replace("value", "")
            elif char == CHAR_PARS.bold.start:
                if "bold" in current_type:
                    current_type = current_type.replace("bold", "")
                else:
                    current_type += "bold"
            elif char == CHAR_PARS.italic.start:
                if "italic" in current_type:
                    current_type = current_type.replace("italic", "")
                else:
                    current_type += "italic"
            elif char == CHAR_PARS.highlight.start:
                if "highlight" in current_type:
                    current_type = current_type.replace("highlight", "")
                else:
                    current_type += "highlight"
            elif char == CHAR_PARS.strike.start:
                if "strike" in current_type:
                    current_type = current_type.replace("strike", "")
                else:
                    current_type += "strike"
            elif char == CHAR_PARS.set_image.start:
                if "set_image" in current_type:
                    current_type = current_type.replace("set_image", "")
                else:
                    current_type += "set_image"
            elif char == CHAR_PARS.play_sound.start:
                if "play_sound" in current_type:
                    current_type = current_type.replace("play_sound", "")
                else:
                    current_type += "play_sound"
        else:
            temp += char
    if temp:
        words.append((temp, current_type))
        temp = ""

    return words


