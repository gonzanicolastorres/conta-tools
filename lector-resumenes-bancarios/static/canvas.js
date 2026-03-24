class CalibrationCanvas {
    constructor(pdfCanvasId, drawCanvasId) {
        this.pdfCanvas = document.getElementById(pdfCanvasId);
        this.drawCanvas = document.getElementById(drawCanvasId);
        this.pdfCtx = this.pdfCanvas.getContext('2d');
        this.drawCtx = this.drawCanvas.getContext('2d');
        
        this.pdfDoc = null;
        this.pageNum = 1;
        this.pageRendering = false;
        this.pageNumPending = null;
        this.scale = 1.3;
        this.pdfUrl = null;

        // Arrays to store line percentages
        this.linesX = [];
        this.linesY = [];
        this.mode = 'x'; // 'x' for vertical columns, 'y' for horizontal active rows

        // Interaction bindings
        this.drawCanvas.addEventListener('mousedown', this.onMouseDown.bind(this));
        this.drawCanvas.addEventListener('contextmenu', this.onContextMenu.bind(this));
    }

    async loadPDF(url) {
        this.pdfUrl = url;
        // The worker is required for parsing the PDF async
        pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
        
        try {
            this.pdfDoc = await pdfjsLib.getDocument(url).promise;
            this.renderPage(this.pageNum);
        } catch (error) {
            console.error('Error loading PDF:', error);
            alert('Error cargando el PDF local');
        }
    }

    renderPage(num) {
        this.pageRendering = true;
        this.pdfDoc.getPage(num).then(page => {
            let viewport = page.getViewport({scale: this.scale});
            // Update both canvases to match the PDF dimensions precisely
            this.pdfCanvas.height = viewport.height;
            this.pdfCanvas.width = viewport.width;
            this.drawCanvas.height = viewport.height;
            this.drawCanvas.width = viewport.width;

            let renderContext = {
                canvasContext: this.pdfCtx,
                viewport: viewport
            };

            page.render(renderContext).promise.then(() => {
                this.pageRendering = false;
                if (this.pageNumPending !== null) {
                    this.renderPage(this.pageNumPending);
                    this.pageNumPending = null;
                }
                this.redrawOverlay();
            });
        });
    }

    zoomIn() { 
        this.scale += 0.2; 
        this.renderPage(this.pageNum); 
    }
    
    zoomOut() { 
        if(this.scale > 0.4) { 
            this.scale -= 0.2; 
            this.renderPage(this.pageNum); 
        } 
    }

    setPage(num) {
        if (this.pdfDoc && num >= 1 && num <= this.pdfDoc.numPages) {
            this.pageNum = num;
            this.renderPage(this.pageNum);
        }
    }

    clearLines() {
        this.linesX = [];
        this.linesY = [];
        this.redrawOverlay();
    }

    setMode(mode) {
        this.mode = mode;
    }

    _getXPercent(e) {
        const rect = this.drawCanvas.getBoundingClientRect();
        return ((e.clientX - rect.left) / rect.width) * 100;
    }

    _getYPercent(e) {
        const rect = this.drawCanvas.getBoundingClientRect();
        return ((e.clientY - rect.top) / rect.height) * 100;
    }

    onMouseDown(e) {
        if(e.button !== 0) return; // Only process left clicks here
        
        if(this.mode === 'x') {
            const pct = this._getXPercent(e);
            // Prevent duplicate clicks in same exact spot
            if(this.linesX.some(p => Math.abs(p - pct) < 0.8)) return;
            this.linesX.push(pct);
            this.linesX.sort((a, b) => a - b);
        } else {
            if(this.linesY.length >= 2) {
                alert("Solo puedes marcar como máximo 2 límites horizontales (Top y Bottom).");
                return;
            }
            const pct = this._getYPercent(e);
            if(this.linesY.some(p => Math.abs(p - pct) < 0.8)) return;
            this.linesY.push(pct);
            this.linesY.sort((a, b) => a - b);
        }
        
        this.redrawOverlay();
    }

    onContextMenu(e) {
        e.preventDefault(); // Prevent native browser context menu
        
        if(this.mode === 'x') {
            if(this.linesX.length === 0) return;
            const pct = this._getXPercent(e);
            // Find closest
            const closest = this.linesX.reduce((prev, curr) => Math.abs(curr - pct) < Math.abs(prev - pct) ? curr : prev);
            // If close enough, remove it
            if(Math.abs(closest - pct) < 3.0) {
                this.linesX = this.linesX.filter(x => x !== closest);
            }
        } else {
            if(this.linesY.length === 0) return;
            const pct = this._getYPercent(e);
            const closest = this.linesY.reduce((prev, curr) => Math.abs(curr - pct) < Math.abs(prev - pct) ? curr : prev);
            if(Math.abs(closest - pct) < 3.0) {
                this.linesY = this.linesY.filter(y => y !== closest);
            }
        }
        
        this.redrawOverlay();
    }

    redrawOverlay() {
        // Clear old drawings
        this.drawCtx.clearRect(0, 0, this.drawCanvas.width, this.drawCanvas.height);
        
        // Draw X Lines (Columns)
        this.drawCtx.lineWidth = 2;
        this.drawCtx.strokeStyle = "#D32F2F";
        this.drawCtx.setLineDash([8, 4]); // Dashed style
        this.drawCtx.fillStyle = "#D32F2F";
        this.drawCtx.font = "bold 14px Arial";
        
        for(let pct of this.linesX) {
            let x = (pct / 100) * this.drawCanvas.width;
            this.drawCtx.beginPath();
            this.drawCtx.moveTo(x, 0);
            this.drawCtx.lineTo(x, this.drawCanvas.height);
            this.drawCtx.stroke();
            this.drawCtx.fillText(pct.toFixed(1) + "%", x + 6, 25);
        }

        // Draw Y Lines (Usable rows boundary)
        this.drawCtx.strokeStyle = "#2E7D32";
        this.drawCtx.fillStyle = "#2E7D32";
        this.drawCtx.lineWidth = 3;
        for(let pct of this.linesY) {
            let y = (pct / 100) * this.drawCanvas.height;
            this.drawCtx.beginPath();
            this.drawCtx.moveTo(0, y);
            this.drawCtx.lineTo(this.drawCanvas.width, y);
            this.drawCtx.stroke();
            this.drawCtx.fillText("Top/Bottom: " + pct.toFixed(1) + "%", 20, y - 10);
        }

        // Emitir un evento para actualización de estado global
        this.drawCanvas.dispatchEvent(new CustomEvent('linesChanged', {
            detail: { x: this.linesX.length, y: this.linesY.length },
            bubbles: true
        }));
    }
}
