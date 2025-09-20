// WorkflowMVP Web Interface JavaScript

let currentWorkflowPath = null;
let parsedSteps = [];
let stepsEdited = false;

// Load tools on page load
fetch('/api/tools')
    .then(response => response.json())
    .then(tools => {
        const toolsDiv = document.getElementById('tools');
        tools.forEach(tool => {
            const toolDiv = document.createElement('div');
            toolDiv.className = 'tool';
            toolDiv.innerHTML = `
                <strong>${tool.name}</strong><br>
                <small>${tool.description}</small><br>
                <small>Parameters: ${Object.keys(tool.parameters).join(', ')}</small>
            `;
            toolsDiv.appendChild(toolDiv);
        });
    });

// Load examples on page load
fetch('/api/examples')
    .then(response => response.json())
    .then(examples => {
        const examplesDiv = document.getElementById('examples');
        examples.forEach(example => {
            const exampleDiv = document.createElement('div');
            exampleDiv.className = 'example';
            exampleDiv.innerHTML = `
                <h4>${example.name}</h4>
                <p>${example.description}</p>
            `;
            exampleDiv.onclick = () => {
                document.getElementById('workflowText').value = example.workflow;
                parseWorkflow();
            };
            examplesDiv.appendChild(exampleDiv);
        });
    });

function parseWorkflow() {
    const inputType = document.querySelector('input[name="inputType"]:checked').value;
    
    if (inputType === 'text') {
        const workflowText = document.getElementById('workflowText').value;
        if (!workflowText.trim()) {
            showError('Please enter a workflow description');
            return;
        }
        parseTextWorkflow(workflowText);
    } else {
        const videoFile = document.getElementById('videoFile').files[0];
        if (!videoFile) {
            showError('Please select a video file');
            return;
        }
        parseVideoWorkflow(videoFile);
    }
}

function parseTextWorkflow(workflowText) {
    showLoading('Parsing workflow...');
    
    fetch('/api/parse-workflow', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({workflow_text: workflowText})
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            parsedSteps = data.steps;
            stepsEdited = false;
            displaySteps(data.steps);
            const generateBtn = document.getElementById('generateBtn');
            generateBtn.disabled = false;
            generateBtn.textContent = 'Generate Python Code';
            generateBtn.style.background = '#007bff';
            showSuccess(`Parsed ${data.steps.length} workflow steps`);
        } else {
            showError('Failed to parse workflow: ' + data.error);
        }
    })
    .catch(error => {
        showError('Error parsing workflow: ' + error.message);
    });
}

function parseVideoWorkflow(videoFile) {
    showLoading('Processing video...');
    
    const formData = new FormData();
    formData.append('video', videoFile);
    
    fetch('/api/parse-video', {
        method: 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            parsedSteps = data.steps;
            stepsEdited = false;
            displaySteps(data.steps);
            const generateBtn = document.getElementById('generateBtn');
            generateBtn.disabled = false;
            generateBtn.textContent = 'Generate Python Code';
            generateBtn.style.background = '#007bff';
            showSuccess(`Parsed ${data.steps.length} workflow steps from video`);
        } else {
            showError('Failed to parse video: ' + data.error);
        }
    })
    .catch(error => {
        showError('Error processing video: ' + error.message);
    });
}

function displaySteps(steps) {
    const stepsDiv = document.getElementById('parsedSteps');
    stepsDiv.innerHTML = '';
    
    steps.forEach((step, index) => {
        const stepDiv = document.createElement('div');
        stepDiv.className = 'step editable-step';
        stepDiv.innerHTML = `
            <div class="step-header">
                <strong>Step ${index + 1}:</strong>
                <button class="edit-btn" onclick="toggleEdit(${index})">✏️ Edit</button>
            </div>
            <div class="step-content">
                <div class="step-display" id="step-display-${index}">
                    <div class="step-description">${step.description}</div>
                    <small>Action: ${step.action} | Dependencies: ${step.dependencies.join(', ') || 'None'}</small>
                </div>
                <div class="step-edit" id="step-edit-${index}" style="display: none;">
                    <textarea class="edit-description" id="edit-desc-${index}" placeholder="Edit step description...">${step.description}</textarea>
                    <div class="edit-actions">
                        <button class="save-btn" onclick="saveStep(${index})">💾 Save</button>
                        <button class="cancel-btn" onclick="cancelEdit(${index})">❌ Cancel</button>
                    </div>
                </div>
            </div>
        `;
        stepsDiv.appendChild(stepDiv);
    });
}

function toggleEdit(stepIndex) {
    const displayDiv = document.getElementById(`step-display-${stepIndex}`);
    const editDiv = document.getElementById(`step-edit-${stepIndex}`);
    
    if (displayDiv.style.display === 'none') {
        // Switch to display mode
        displayDiv.style.display = 'block';
        editDiv.style.display = 'none';
    } else {
        // Switch to edit mode
        displayDiv.style.display = 'none';
        editDiv.style.display = 'block';
        // Focus on the textarea
        document.getElementById(`edit-desc-${stepIndex}`).focus();
    }
}

function saveStep(stepIndex) {
    const newDescription = document.getElementById(`edit-desc-${stepIndex}`).value.trim();
    if (!newDescription) {
        showError('Step description cannot be empty');
        return;
    }
    
    // Update the parsed steps array
    parsedSteps[stepIndex].description = newDescription;
    stepsEdited = true;
    
    // Update the display
    const descriptionDiv = document.querySelector(`#step-display-${stepIndex} .step-description`);
    descriptionDiv.textContent = newDescription;
    
    // Switch back to display mode
    toggleEdit(stepIndex);
    
    showSuccess(`Step ${stepIndex + 1} updated successfully`);
    
    // Update generate button to show edits were made
    const generateBtn = document.getElementById('generateBtn');
    if (stepsEdited) {
        generateBtn.textContent = 'Generate Python Code (Modified)';
        generateBtn.style.background = '#ffc107';
    }
}

function cancelEdit(stepIndex) {
    // Reset the textarea to original value
    document.getElementById(`edit-desc-${stepIndex}`).value = parsedSteps[stepIndex].description;
    
    // Switch back to display mode
    toggleEdit(stepIndex);
}

function generateWorkflow() {
    if (parsedSteps.length === 0) {
        showError('No parsed steps to generate from');
        return;
    }

    // Auto-generate workflow name based on timestamp
    const workflowName = `workflow_${Date.now()}`;


    showLoading('Generating Python code...');
    
    fetch('/api/generate-workflow', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            steps: parsedSteps,
            name: workflowName
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            currentWorkflowPath = data.output_path;
            document.getElementById('runBtn').disabled = false;
            showSuccess('Python code generated successfully!');
        } else {
            showError('Failed to generate code: ' + data.error);
        }
    })
    .catch(error => {
        showError('Error generating code: ' + error.message);
    });
}

function runWorkflow() {
    if (!currentWorkflowPath) {
        showError('No workflow to run');
        return;
    }

    showLoading('Running workflow...');
    
    fetch('/api/run-workflow', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({workflow_path: currentWorkflowPath})
    })
    .then(response => response.json())
    .then(data => {
        const resultsDiv = document.getElementById('runResults');
        if (data.success) {
            resultsDiv.innerHTML = `
                <div class="success">✅ Workflow completed successfully!</div>
                <pre>${data.stdout}</pre>
            `;
        } else {
            resultsDiv.innerHTML = `
                <div class="error">❌ Workflow failed!</div>
                <pre>${data.stderr || data.error}</pre>
            `;
        }
    })
    .catch(error => {
        showError('Error running workflow: ' + error.message);
    });
}

function showError(message) {
    const resultsDiv = document.getElementById('runResults');
    resultsDiv.innerHTML = `<div class="error">${message}</div>`;
}

function showSuccess(message) {
    const resultsDiv = document.getElementById('runResults');
    resultsDiv.innerHTML = `<div class="success">${message}</div>`;
}

function showLoading(message) {
    const resultsDiv = document.getElementById('runResults');
    resultsDiv.innerHTML = `<div class="loading">${message}</div>`;
}

function toggleInputType() {
    const textInput = document.getElementById('textInput');
    const videoInput = document.getElementById('videoInput');
    const inputType = document.querySelector('input[name="inputType"]:checked').value;
    
    if (inputType === 'text') {
        textInput.style.display = 'block';
        videoInput.style.display = 'none';
    } else {
        textInput.style.display = 'none';
        videoInput.style.display = 'block';
    }
}

function handleVideoUpload() {
    const videoFile = document.getElementById('videoFile').files[0];
    const videoPreview = document.getElementById('videoPreview');
    const previewVideo = document.getElementById('previewVideo');
    
    if (videoFile) {
        const url = URL.createObjectURL(videoFile);
        previewVideo.src = url;
        videoPreview.style.display = 'block';
    } else {
        videoPreview.style.display = 'none';
    }
}

// Add event listener for video file input
document.addEventListener('DOMContentLoaded', function() {
    document.getElementById('videoFile').addEventListener('change', handleVideoUpload);
});
