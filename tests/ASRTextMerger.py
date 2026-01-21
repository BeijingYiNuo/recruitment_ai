class ASRTextMerger:
    def __init__(self):
        self.last_text = ""
    


    def diff(self, new_text: str) -> str | None:
        if not new_text:
            return None
        
        if new_text == self.last_text:
            return None
        
        if new_text.startswith(self.last_text):
            delta = new_text[len(self.last_text):]
            self.last_text = new_text
            return delta if delta.strip() else None
        
        self.last_text = new_text
        return new_text