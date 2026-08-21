import Foundation
import ImageIO
import Vision

struct OCRLine: Codable {
    let text: String
    let confidence: Float
    let x: Double
    let y: Double
    let width: Double
    let height: Double
}

struct OCRResult: Codable {
    let schemaVersion: Int
    let engine: String
    let recognitionLevel: String
    let languageCorrection: Bool
    let lines: [OCRLine]
    let text: String
    let meanConfidence: Double?
}

func fail(_ message: String) -> Never {
    FileHandle.standardError.write(Data((message + "\n").utf8))
    exit(2)
}

guard CommandLine.arguments.count == 2 else {
    fail("usage: macos_vision_ocr <image>")
}

let imageURL = URL(fileURLWithPath: CommandLine.arguments[1])
guard let source = CGImageSourceCreateWithURL(imageURL as CFURL, nil),
      let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
    fail("unable to decode image")
}

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = true

do {
    try VNImageRequestHandler(cgImage: image, options: [:]).perform([request])
} catch {
    fail("Vision request failed: \(error)")
}

let observations = request.results ?? []
let lines: [OCRLine] = observations.compactMap { observation in
    guard let candidate = observation.topCandidates(1).first else { return nil }
    let box = observation.boundingBox
    return OCRLine(
        text: candidate.string,
        confidence: candidate.confidence,
        x: box.origin.x,
        y: box.origin.y,
        width: box.size.width,
        height: box.size.height
    )
}.sorted { left, right in
    if abs(left.y - right.y) > 0.01 { return left.y > right.y }
    return left.x < right.x
}

let confidence = lines.isEmpty
    ? nil
    : lines.map { Double($0.confidence) }.reduce(0, +) / Double(lines.count)
let result = OCRResult(
    schemaVersion: 1,
    engine: "apple_vision_vnrecognizetextrequest",
    recognitionLevel: "accurate",
    languageCorrection: true,
    lines: lines,
    text: lines.map { $0.text }.joined(separator: "\n"),
    meanConfidence: confidence
)

do {
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.sortedKeys]
    FileHandle.standardOutput.write(try encoder.encode(result))
    FileHandle.standardOutput.write(Data("\n".utf8))
} catch {
    fail("unable to encode OCR result: \(error)")
}
