// Format time from HH:MM:SS to HH:MM
export function formatTime(time) {
    return time.substring(0, 5);
}

// Format duration from minutes to "X min"
export function formatDuration(minutes) {
    return `${minutes} min`;
}

// Format a list of service days
export function formatServiceDays(days) {
    if (!days || days.length === 0) return '';
    if (days.length === 7) return 'Every day';
    
    const weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'];
    const weekend = ['Saturday', 'Sunday'];
    
    const hasAllWeekdays = weekdays.every(day => days.includes(day));
    const hasAllWeekend = weekend.every(day => days.includes(day));
    
    if (hasAllWeekdays && !hasAllWeekend) return 'Weekdays';
    if (!hasAllWeekdays && hasAllWeekend) return 'Weekend';
    
    return days.join(', ');
}

// Convert RGB to LAB color space
export function rgb2lab(rgb) {
    let r = rgb[0] / 255;
    let g = rgb[1] / 255;
    let b = rgb[2] / 255;

    r = r > 0.04045 ? Math.pow((r + 0.055) / 1.055, 2.4) : r / 12.92;
    g = g > 0.04045 ? Math.pow((g + 0.055) / 1.055, 2.4) : g / 12.92;
    b = b > 0.04045 ? Math.pow((b + 0.055) / 1.055, 2.4) : b / 12.92;

    let x = (r * 0.4124 + g * 0.3576 + b * 0.1805) * 100;
    let y = (r * 0.2126 + g * 0.7152 + b * 0.0722) * 100;
    let z = (r * 0.0193 + g * 0.1192 + b * 0.9505) * 100;

    x = x / 95.047;
    y = y / 100.000;
    z = z / 108.883;

    x = x > 0.008856 ? Math.pow(x, 1/3) : (7.787 * x) + 16/116;
    y = y > 0.008856 ? Math.pow(y, 1/3) : (7.787 * y) + 16/116;
    z = z > 0.008856 ? Math.pow(z, 1/3) : (7.787 * z) + 16/116;

    return [(116 * y) - 16, 500 * (x - y), 200 * (y - z)];
}

// Calculate color difference in LAB color space
export function deltaE(lab1, lab2) {
    const deltaL = lab1[0] - lab2[0];
    const deltaA = lab1[1] - lab2[1];
    const deltaB = lab1[2] - lab2[2];
    return Math.sqrt(deltaL * deltaL + deltaA * deltaA + deltaB * deltaB);
}

// Sort colors by luminance
export function sortColors(colors) {
    return [...colors].sort((a, b) => {
        const lumA = 0.2126 * a[0] + 0.7152 * a[1] + 0.0722 * a[2];
        const lumB = 0.2126 * b[0] + 0.7152 * b[1] + 0.0722 * b[2];
        return lumA - lumB;
    });
}

// Generate distinct colors using simulated annealing
export function simulatedAnnealing(colors, selectCount, settings = {}) {
    console.log('Starting Simulated Annealing calculation...');
    const start = performance.now();
    
    const labColors = colors.map(rgb2lab);
    const maxIterations = 10000;
    const initialTemp = settings.initialTemp ?? 1000;
    const coolingRate = settings.coolingRate ?? 0.995;
    const minTemp = settings.minTemp ?? 0.1;
    
    // Helper function to calculate minimum distance between selected colors
    function calculateFitness(selection) {
        let minDist = Infinity;
        for (let i = 0; i < selection.length - 1; i++) {
            for (let j = i + 1; j < selection.length; j++) {
                const dist = deltaE(labColors[selection[i]], labColors[selection[j]]);
                minDist = Math.min(minDist, dist);
            }
        }
        return minDist;
    }
    
    // Generate initial solution
    let currentSolution = Array.from({length: colors.length}, (_, i) => i)
        .sort(() => Math.random() - 0.5)
        .slice(0, selectCount);
    let currentFitness = calculateFitness(currentSolution);
    let bestSolution = [...currentSolution];
    let bestFitness = currentFitness;
    
    let temperature = initialTemp;
    
    // Main loop
    for (let i = 0; i < maxIterations && temperature > minTemp; i++) {
        // Generate neighbor by swapping one selected color with an unselected one
        const neighborSolution = [...currentSolution];
        const swapIndex = Math.floor(Math.random() * selectCount);
        const availableIndices = Array.from({length: colors.length}, (_, i) => i)
            .filter(i => !currentSolution.includes(i));
        const newIndex = availableIndices[Math.floor(Math.random() * availableIndices.length)];
        neighborSolution[swapIndex] = newIndex;
        
        const neighborFitness = calculateFitness(neighborSolution);
        
        // Decide if we should accept the neighbor
        const delta = neighborFitness - currentFitness;
        if (delta > 0 || Math.random() < Math.exp(delta / temperature)) {
            currentSolution = neighborSolution;
            currentFitness = neighborFitness;
            
            if (currentFitness > bestFitness) {
                bestSolution = [...currentSolution];
                bestFitness = currentFitness;
            }
        }
        
        temperature *= coolingRate;
    }
    
    return {
        colors: sortColors(bestSolution.map(i => colors[i])),
        time: performance.now() - start
    };
}

// Random color selection (alternative to simulated annealing)
export function randomSelection(colors, selectCount) {
    console.log('Starting Random Selection...');
    const start = performance.now();
    
    // Randomly select indices without replacement
    const indices = Array.from({length: colors.length}, (_, i) => i);
    const selected = [];
    for (let i = 0; i < selectCount; i++) {
        const randomIndex = Math.floor(Math.random() * indices.length);
        selected.push(indices[randomIndex]);
        indices.splice(randomIndex, 1);
    }
    
    return {
        colors: sortColors(selected.map(i => colors[i])),
        time: performance.now() - start
    };
}

// Convert RGB array to hex color string
export function rgbToHex(rgb) {
    return '#' + rgb.map(x => {
        const hex = Math.round(x).toString(16);
        return hex.length === 1 ? '0' + hex : hex;
    }).join('');
}

// Convert hex color to RGB array
export function hexToRgb(hex) {
    const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
    return result ? [
        parseInt(result[1], 16),
        parseInt(result[2], 16),
        parseInt(result[3], 16)
    ] : null;
} 