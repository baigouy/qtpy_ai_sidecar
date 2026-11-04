"""Tools menu > Embeddings…: choose the optional embeddings source (see embeddings.py)."""
from qtpy.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
                            QLineEdit, QPushButton)
from . import embeddings

LABELS = (('off', 'Off'), ('mistral', 'Mistral AI API (mistral-embed)'),
          ('local', 'Local server (llama.cpp, Ollama, LM Studio)'))
NOTES = {
    'off': 'Applications that need embeddings (litsearch\'s PDF index) use their own source.',
    'mistral': 'Sends the texts to embed (for litsearch, the full text of your indexed PDFs) to Mistral, '
               'with the key stored for the Mistral chat provider; PyFigures\' image search also sends '
               'small thumbnails of your images to the image-description model. Check that your '
               'agreement covers unpublished material.',
    'local': 'Any OpenAI-compatible /v1/embeddings server on this computer, e.g. '
             'llama-server -m nomic-embed-text-v1.5.Q8_0.gguf --embedding --port 8081. Nothing leaves it. '
             'Image descriptions need a vision model on that server (leave empty for none).'}


class EmbeddingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Embeddings')
        form = QFormLayout(self)
        self.source = QComboBox()
        for key, label in LABELS:
            self.source.addItem(label, key)
        self.model = QLineEdit()
        self.url = QLineEdit()
        self.vision = QLineEdit()
        self.vision.setToolTip('A vision model that describes pictures in words for image search '
                               '(PyFigures); empty: the default (Mistral) or none (local)')
        form.addRow('Source:', self.source)
        form.addRow('Model:', self.model)
        form.addRow('Address:', self.url)
        form.addRow('Image descriptions:', self.vision)
        self.note = QLabel()
        self.note.setWordWrap(True)
        form.addRow(self.note)
        self.result = QLabel()
        self.result.setWordWrap(True)
        test = QPushButton('Test')
        test.setToolTip('Embed one sentence with these settings')
        test.clicked.connect(self.test)
        form.addRow(test, self.result)
        form.addRow(QLabel('An index built with one model can only be searched with that model: '
                           'changing it means re-indexing.'))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        saved = embeddings.load()
        self.source.setCurrentIndex(self.source.findData(saved['source']))
        if saved['source'] != 'off':
            self.model.setText(saved['model'])
            self.url.setText(saved['base_url'])
            self.vision.setText(saved['vision_model'])
        self.changed(keep=True)
        self.source.currentIndexChanged.connect(lambda _: self.changed())

    def settings(self):
        return {'source': self.source.currentData(), 'model': self.model.text(), 'base_url': self.url.text(),
                'vision_model': self.vision.text()}

    def changed(self, keep=False):
        source = self.source.currentData()
        on = source != 'off'
        self.model.setEnabled(on)
        self.url.setEnabled(source == 'local')
        self.vision.setEnabled(on)
        if on and not (keep and self.model.text()):
            self.model.setText(embeddings.DEFAULTS[source]['model'])
            self.url.setText(embeddings.DEFAULTS[source]['base_url'])
            self.vision.setText(embeddings.DEFAULTS[source]['vision_model'])
        if not on:
            self.model.clear()
            self.url.clear()
            self.vision.clear()
        self.note.setText(NOTES[source])
        self.result.clear()

    def test(self):
        try:
            if self.source.currentData() == 'off':
                raise ValueError('Embeddings are off')
            [vector] = embeddings.Embedder(self.settings(), timeout=20).embed(['A test sentence.'])
            self.result.setText(f'Works: {len(vector)} numbers per text.')
        except Exception as exc:
            self.result.setText('Failed: ' + str(exc))

    def accept(self):
        try:
            embeddings.save(self.settings())
        except ValueError as exc:
            self.result.setText(str(exc))
            return
        super().accept()
