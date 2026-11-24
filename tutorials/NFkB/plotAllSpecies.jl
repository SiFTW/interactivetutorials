using Statistics

function plotAllSpecies(speciesToPlot,conditionsToPlot,colorArray,first_cell,last_cell,folder,hoursToPlot,maxValOfYAxis,qualityScaling,preStimTime)
    allConditionsArray=[]
    n_cells = last_cell - first_cell + 1

    for species in speciesToPlot
        thisPlotStd = plot(title="Time Course", grid=false, framestyle=:axes)
        boxPlotAll  = plot(title="Steady State", grid=false, framestyle=:axes)

        meansOfAllConditions = zeros(length(conditionsToPlot))
        stdOfAllConditions   = zeros(length(conditionsToPlot))
        maxValueOfAllConditions = 0.0
        maxSteadyState = 0.0

        for (conditionIndex, condition) in enumerate(conditionsToPlot)
            firstFile = DataFrame(CSV.File(folder*"/sol_"*condition*"_cell_"*string(first_cell)*".csv"))
            n_tc = size(firstFile, 2) - 1
            totalCols = preStimTime + n_tc
            conditionArray = zeros(n_cells, totalCols)
            lineColor = colorArray[mod1(conditionIndex, length(colorArray))]

            for (rowIdx, i) in enumerate(first_cell:last_cell)
                thisCellData = DataFrame(CSV.File(folder*"/sol_"*condition*"_cell_"*string(i)*".csv"))
                if !("names" in names(thisCellData))
                    insertcols!(thisCellData, 1, :names=>syms)
                end
                allNoneFloats = findall(eltype.(eachcol(thisCellData)) .!= Float64)
                if length(allNoneFloats) > 1
                    for index in allNoneFloats[2:end]
                        if eltype(thisCellData[:, index]) <: AbstractString
                            thisCellData[!, index] = parse.(Float64, thisCellData[:, index])
                        else
                            thisCellData[!, index] = Float64.(thisCellData[:, index])
                        end
                    end
                end

                if endswith(species, "*")
                    speciesShort = species[1:end-1]
                    speciesIDs = intersect(
                        findall(x -> occursin(speciesShort, x), syms),
                        findall(x -> !startswith(x, "t"), syms),
                    )
                    speciesNames = String.(syms[speciesIDs])
                    thisTC = zeros(size(thisCellData, 2) - 1)
                    for thisName in speciesNames
                        thisSpeciesTC = vec(Float64.(Matrix(thisCellData[thisCellData[!, :names] .== thisName, 2:end])))
                        thisTC .+= thisSpeciesTC
                    end
                else
                    thisTC = vec(Float64.(Matrix(thisCellData[thisCellData[!, :names] .== species, 2:end])))
                end

                entriesToSave = min(length(thisTC), n_tc)
                # Pre-stimulation steady-state baseline followed by dynamic time course
                conditionArray[rowIdx, 1:preStimTime] .= thisTC[1]
                conditionArray[rowIdx, preStimTime+1:preStimTime+entriesToSave] = thisTC[1:entriesToSave]
            end

            push!(allConditionsArray, conditionArray)

            # Compute mean and standard deviation across simulated cells
            if n_cells > 1
                meanOfCondition = vec(mean(conditionArray, dims=1))
                stdOfCondition  = vec(std(conditionArray, dims=1))
            else
                meanOfCondition = vec(conditionArray)
                stdOfCondition  = zeros(length(meanOfCondition))
            end

            # Clamp lower ribbon visually at 0 so concentrations never shade below zero
            lowerRibbon = min.(stdOfCondition, meanOfCondition)
            upperRibbon = stdOfCondition

            largestValForGraph = maximum(meanOfCondition .+ upperRibbon)
            if largestValForGraph > maxValueOfAllConditions
                maxValueOfAllConditions = largestValForGraph
            end

            timeHours = ((1:totalCols) .- preStimTime) ./ 60.0
            plot!(
                thisPlotStd,
                timeHours,
                meanOfCondition;
                ribbon=(lowerRibbon, upperRibbon),
                fillalpha=0.22,
                color=lineColor,
                label=condition,
                linewidth=3,
            )

            ssMean = meanOfCondition[preStimTime]
            ssStd  = stdOfCondition[preStimTime]
            meansOfAllConditions[conditionIndex] = ssMean
            stdOfAllConditions[conditionIndex]   = ssStd
            if ssMean + ssStd > maxSteadyState
                maxSteadyState = ssMean + ssStd
            end
        end

        # Left panel: Steady-state mean markers with crisp black +/- SD error bars
        for (conditionIndex, condition) in enumerate(conditionsToPlot)
            lineColor = colorArray[mod1(conditionIndex, length(colorArray))]
            scatter!(
                boxPlotAll,
                [conditionIndex],
                [meansOfAllConditions[conditionIndex]];
                yerror=[stdOfAllConditions[conditionIndex]],
                markercolor=lineColor,
                markerstrokecolor=:black,
                markerstrokewidth=1.8,
                linecolor=:black,
                linewidth=2,
                markersize=max(5, round(Int, 12 * qualityScaling)),
                label=false,
            )
        end

        plot!(
            boxPlotAll;
            xticks=(1:length(conditionsToPlot), conditionsToPlot),
            xrotation=60,
            xlim=(0.3, length(conditionsToPlot) + 0.7),
            ylabel=species,
            xtickfontsize=10,
            ytickfontsize=11,
            yguidefontsize=12,
            titlefontsize=12,
        )

        xTickStep = max(1, round(Int, hoursToPlot / 4))
        plot!(
            thisPlotStd;
            xticks=collect(0:xTickStep:hoursToPlot),
            xlim=(-preStimTime / 60.0, hoursToPlot),
            xlabel="Time (h)",
            xtickfontsize=11,
            ytickfontsize=11,
            xguidefontsize=12,
            titlefontsize=12,
            legendfontsize=10,
        )

        if maxValOfYAxis > 0
            plot!(thisPlotStd, ylim=(0, maxValOfYAxis))
            plot!(boxPlotAll, ylim=(0, max(maxSteadyState * 1.12, maxValOfYAxis)))
        else
            plot!(thisPlotStd, ylim=(0, max(maxValueOfAllConditions * 1.08, 1e-6)))
            plot!(boxPlotAll, ylim=(0, max(maxSteadyState * 1.15, 0.1)))
        end

        p1 = plot(
            boxPlotAll,
            thisPlotStd;
            layout=grid(1, 2, widths=[0.32, 0.68]),
            size=(round(Int, 1600 * qualityScaling), round(Int, 900 * qualityScaling)),
            dpi=200,
            plot_title=species,
            plot_titlefontsize=13,
        )
        display(p1)
    end
end
